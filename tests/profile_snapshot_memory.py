"""Profile snapshot and Git-review memory on a deterministic service fixture.

Run from the repository root with ``python3 tests/profile_snapshot_memory.py``.
This is a diagnostic benchmark, not an accuracy or performance gate. Process
CPU and traced allocations include all Python threads during overlapping work.
"""

from __future__ import annotations

import gc
import json
import resource
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from threadline.changes import review_changes
from threadline.analyzer import Analyzer
from threadline.service import SnapshotStore
from threadline.workflows import workflow_catalog


def make_fixture(root: Path) -> int:
    for module_index in range(40):
        lines = [
            "FEE = 1.05",
            "class Repo:",
            "    def get(self, value):",
            "        return value + 1",
            "class Service:",
            "    def __init__(self, repo: Repo):",
            "        self.repo = repo",
            "    def run(self, value):",
            "        if value > 0:",
            "            return self.repo.get(value)",
            "        return value",
        ]
        for function_index in range(20):
            lines.extend(
                [
                    f"def step_{function_index}(value):",
                    "    if value > 0:",
                    "        return Service(Repo()).run(value)",
                    "    return value",
                ]
            )
        lines.extend(["def entry(value):", "    return step_0(value)"])
        (root / f"module_{module_index:02d}.py").write_text("\n".join(lines) + "\n")

    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "profile@example.invalid"],
        ["git", "config", "user.name", "Profile"],
        ["git", "add", "."],
        ["git", "commit", "-qm", "baseline"],
    ):
        subprocess.run(command, cwd=root, check=True)
    return sum(path.stat().st_size for path in root.glob("*.py"))


def measure(label: str, action, *, operations: int = 1, reset_peak: bool = True):
    before_current, _ = tracemalloc.get_traced_memory()
    if reset_peak:
        tracemalloc.reset_peak()
    started = time.perf_counter()
    cpu_started = time.process_time()
    value = action()
    current, peak = tracemalloc.get_traced_memory()
    print(
        json.dumps(
            {
                "phase": label,
                "seconds": round(time.perf_counter() - started, 3),
                "processCpuSeconds": round(time.process_time() - cpu_started, 3),
                "operations": operations,
                "currentMiB": round(current / (1024 * 1024), 2),
                "peakMiB": round(peak / (1024 * 1024), 2),
                "deltaMiB": round((current - before_current) / (1024 * 1024), 2),
                "peakScope": "shared process" if not reset_peak else "phase",
            }
        )
    )
    return value


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="threadline-memory-") as directory:
        root = Path(directory)
        source_bytes = make_fixture(root)
        gc.collect()
        tracemalloc.start()
        store = SnapshotStore(root, retention=2)

        parser = Analyzer(root)
        measure("discovery + parse only", parser.discover)
        assert len(parser.files) == 40
        del parser
        gc.collect()

        model = measure("initial refresh", store.refresh)
        original_snapshot_id = model["snapshotId"]
        catalog = measure("catalog rebuild", lambda: workflow_catalog(model))
        assert len(catalog) == len(model["catalog"])
        del catalog
        gc.collect()
        entry = next(
            scope["id"]
            for scope in model["scopes"].values()
            if scope["qualified"] == "entry" and scope["file"] == "module_00.py"
        )
        workflow = measure("cold workflow generation", lambda: store.get_workflow(entry))
        workflow_cache_bytes_after_query = store._workflow_cache_bytes
        def cached_workflow_responses():
            for _ in range(100):
                store.get_workflow(entry)

        measure("100 cached workflow responses", cached_workflow_responses, operations=100)
        measure("summary + scope + source", lambda: (
            store.summary(), store.get_scope(entry),
            store.get_source(file="module_00.py", start=1, end=20)))

        def serialize_workflow():
            encoded = bytearray()
            for chunk in json.JSONEncoder(ensure_ascii=False).iterencode(workflow):
                encoded.extend(chunk.encode("utf-8"))
            return len(encoded)

        workflow_response_bytes = measure("serialize workflow response", serialize_workflow)
        changed_file = root / "module_00.py"
        changed_file.write_text(changed_file.read_text().replace("FEE = 1.05", "FEE = 1.08", 1))

        refresh_started = threading.Event()
        original_discover = Analyzer.discover

        def signal_after_discovery(analyzer):
            result = original_discover(analyzer)
            refresh_started.set()
            return result

        def refresh_with_pinned_read():
            with patch.object(Analyzer, "discover", signal_after_discovery):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(store.refresh)
                    assert refresh_started.wait(timeout=10)

                    def pinned_read():
                        for _ in range(25):
                            scope = store.get_scope(entry, snapshot_id=original_snapshot_id)
                            source = store.get_source(
                                snapshot_id=original_snapshot_id,
                                file="module_00.py", start=1, end=11,
                            )
                            assert scope["snapshotId"] == original_snapshot_id
                            assert source["source"].startswith("FEE = 1.05")

                    measure("25 pinned reads during refresh", pinned_read,
                            operations=25, reset_peak=False)
                    pending_at_end = not future.done()
                    refreshed = future.result()
            return refreshed, pending_at_end

        refreshed_model, refresh_pending_at_pinned_end = measure(
            "refresh retaining prior snapshot", refresh_with_pinned_read)
        assert refreshed_model["snapshotId"] != original_snapshot_id
        assert len(store._models) == 2
        assert refresh_pending_at_pinned_end
        measure("retained prior snapshot read", lambda: store.get_scope(
            entry, snapshot_id=original_snapshot_id))
        review = measure("Git change review", lambda: review_changes(root, store=store))
        rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_mib = rss_kib / (1024 * 1024) if sys.platform == "darwin" else rss_kib / 1024
        serialized_model_bytes = measure("serialize retained model", lambda: len(
            json.dumps(model, ensure_ascii=False, separators=(",", ":")).encode("utf-8")))

        print(
            json.dumps(
                {
                    "fixture": "40 files, 20 step functions plus Repo, Service, entry per file",
                    "sourceBytes": source_bytes,
                    "parsedFiles": model["coverage"]["files"],
                    "definitions": model["coverage"]["definitions"],
                    "calls": model["coverage"]["calls"],
                    "serializedModelBytes": serialized_model_bytes,
                    "workflowResponseBytes": workflow_response_bytes,
                    "retainedSnapshots": len(store._models),
                    "workflowCacheBytesAfterQuery": workflow_cache_bytes_after_query,
                    "changeFiles": len(review["files"]),
                    "refreshPendingAtPinnedReadEnd": refresh_pending_at_pinned_end,
                    "ruMaxRssMiBBeforeSerialization": round(rss_mib, 2),
                    "platform": sys.platform,
                    "pythonVersion": sys.version.split()[0],
                }
            )
        )


if __name__ == "__main__":
    main()
