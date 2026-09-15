#!/usr/bin/env python3
"""Clone pinned public Python repositories and validate Threadline's review contract.

The target projects are never installed, imported, or executed. Only Git and
Threadline's source parser touch their working trees.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from threadline.service import SnapshotStore

ALLOWED_STATUSES = {"supported", "possible", "external", "unknown"}


class ValidationFailure(AssertionError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationFailure(message)


def git(root: Path, *args: str, capture: bool = True) -> str:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        env=env,
        timeout=120,
    )
    return result.stdout.strip() if capture else ""


def checkout(spec: dict[str, Any], destination: Path, offline: bool) -> None:
    if not (destination / ".git").is_dir():
        require(not destination.exists() or not any(destination.iterdir()),
                f"cache destination is not an empty Git checkout: {destination}")
        destination.mkdir(parents=True, exist_ok=True)
        git(destination, "init", "-q")
        git(destination, "remote", "add", "origin", spec["url"])
    require(not git(destination, "status", "--porcelain", "--untracked-files=all"),
            f"cached checkout has local changes: {destination}")
    revision = spec["revision"]
    present = subprocess.run(
        ["git", "-C", str(destination), "cat-file", "-e", f"{revision}^{{commit}}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0
    if not present:
        require(not offline, f"revision {revision} is absent from offline cache for {spec['name']}")
        git(destination, "fetch", "-q", "--depth", "1", "origin", revision)
    git(destination, "checkout", "-q", "--detach", revision)
    require(git(destination, "rev-parse", "HEAD") == revision,
            f"{spec['name']} did not check out the pinned revision")


def pages(fetch) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor = 0
    while True:
        page = fetch(cursor)
        items.extend(page["items"])
        if page["nextCursor"] is None:
            return items
        cursor = page["nextCursor"]


def validate_repository(spec: dict[str, Any], target: Path) -> dict[str, Any]:
    attempted_target_imports: list[str] = []
    forbidden = tuple(spec.get("forbiddenImports", ()))

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "import" and args:
            name = str(args[0])
            if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                attempted_target_imports.append(name)
                raise ValidationFailure(f"Target import blocked: {name}")

    sys.addaudithook(audit)
    before = git(target, "status", "--porcelain", "--untracked-files=all")
    started = time.perf_counter()
    store = SnapshotStore(target, source_roots=spec.get("sourceRoots"), exclude=spec.get("exclude"))
    summary = store.summary(limit=100)
    analysis_seconds = time.perf_counter() - started
    require(analysis_seconds <= spec.get('budgets', {}).get('analysisSeconds', 60),
            f'analysis exceeded budget: {analysis_seconds:.3f}s')
    query_started = time.perf_counter()
    snapshot = summary["snapshotId"]
    coverage = summary["coverage"]

    require(summary["diagnostics"]["parseErrors"]["total"] == 0,
            "repository contains source Threadline could not parse")
    require(coverage["statements"] == coverage["representedStatements"],
            "not every parsed statement is represented")
    require(coverage["calls"] == coverage["representedCalls"] + coverage["unmodeledCalls"],
            "call accounting is inconsistent")

    expected = spec["reviewSymbol"]
    symbols = pages(lambda cursor: store.find_symbols(
        expected["qualified"], snapshot_id=snapshot, cursor=cursor, limit=100
    )["symbols"])
    matches = [item for item in symbols
               if item["qualified"] == expected["qualified"] and item["file"] == expected["file"]]
    require(len(matches) == 1,
            f"expected one {expected['qualified']} in {expected['file']}; found {len(matches)}")
    symbol = matches[0]

    method = store.get_method(symbol["id"], snapshot_id=snapshot, limit=100)
    require(isinstance(method["inputs"], list) and isinstance(method["output"], dict),
            "method input/output payload is absent")
    require(method["operations"]["total"] > 0, "selected method has no visible operations")
    source = store.get_source(snapshot_id=snapshot, evidence=symbol["evidenceId"])
    from threadline.analyzer import Analyzer
    calls = [call for operation in Analyzer.walk_flow(store.model(snapshot)['scopes'][symbol['id']]['flow']) for call in operation['calls']]
    for expectation in spec.get('expectedCalls', []):
        matches = [call for call in calls if call['name'] == expectation['name']]
        require(bool(matches) and all(call['status'] == expectation['status'] for call in matches),
                f"Incorrect call certainty for {expectation['name']}; expected {expectation['status']}")
    require(bool(source["source"].strip()), "selected method evidence returned no source")
    require(source["evidenceId"] == symbol["evidenceId"], "source lost its evidence identity")
    require(source["requestedSpan"]["file"] == expected["file"], "source evidence points to another file")

    stages: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    cursor = 0
    workflow_meta: dict[str, Any] | None = None
    while True:
        workflow = store.get_workflow(symbol["id"], snapshot_id=snapshot, cursor=cursor, limit=100)
        if workflow_meta is None:
            workflow_meta = workflow
        stages.extend(workflow["stages"]["items"])
        links.extend(workflow["links"])
        next_cursor = workflow["stages"]["nextCursor"]
        if next_cursor is None:
            break
        cursor = next_cursor
    require(workflow_meta is not None and not workflow_meta.get("truncated", False),
            "selected workflow hit Threadline's safety truncation")
    require(len(stages) == workflow_meta["stages"]["total"], "workflow pagination lost stages")
    statuses = {stage["status"] for stage in stages}
    require(statuses <= ALLOWED_STATUSES, f"workflow returned invalid statuses: {sorted(statuses)}")
    require(set(spec["requiredStatuses"]) <= statuses,
            f"workflow did not expose expected uncertainty states: {spec['requiredStatuses']}")

    query_seconds = time.perf_counter() - query_started
    require(query_seconds <= spec.get('budgets', {}).get('querySeconds', 3),
            f'query sequence exceeded budget: {query_seconds:.3f}s')
    evidence_checks = 1
    for link in links:
        require(link.get("evidence"), "workflow connection has no source evidence")
        for proof in link["evidence"]:
            evidence_id = proof.get("evidenceId")
            require(bool(evidence_id), "workflow connection has no evidence ID")
            excerpt = store.get_source(snapshot_id=snapshot, evidence=evidence_id)
            require(bool(excerpt["source"].strip()), "workflow evidence returned no original source")
            evidence_checks += 1

    workflow_files = {stage["span"]["file"] for stage in stages if stage.get("span")}
    minimums = spec["minimums"]
    observed = {
        "files": coverage["files"],
        "definitions": coverage["definitions"],
        "branches": method["stats"]["branches"],
        "workflowStages": len(stages),
        "workflowFiles": len(workflow_files),
    }
    for key, minimum in minimums.items():
        require(observed[key] >= minimum, f"{key}={observed[key]} is below required {minimum}")

    require(not attempted_target_imports,
            f"target package import attempted: {sorted(set(attempted_target_imports))}")
    after = git(target, "status", "--porcelain", "--untracked-files=all")
    require(before == after == "", "analysis modified the target repository")

    import resource
    peak_rss_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024 if sys.platform == 'darwin' else 1024)
    require(peak_rss_mib <= spec.get('budgets', {}).get('peakRssMiB', 2048),
            f'peak RSS exceeded budget: {peak_rss_mib:.1f} MiB')
    return {
        "peakRssMiB": round(peak_rss_mib, 1),
        "name": spec["name"],
        "url": spec["url"],
        "revision": spec["revision"],
        "snapshotId": snapshot,
        "elapsedSeconds": round(time.perf_counter() - started, 3),
        "analysisSeconds": round(analysis_seconds, 3),
        "querySeconds": round(query_seconds, 3),
        "parsedFiles": coverage["files"],
        "definitions": coverage["definitions"],
        "statements": coverage["statements"],
        "calls": coverage["calls"],
        "unmodeledCalls": coverage["unmodeledCalls"],
        "suggestedEntrypoints": summary["entrypoints"]["total"],
        "reviewSymbol": expected,
        "branches": method["stats"]["branches"],
        "workflowStages": len(stages),
        "workflowFiles": sorted(workflow_files),
        "statuses": sorted(statuses),
        "evidenceChecks": evidence_checks,
        "sourceTruncated": source["truncated"],
        "targetImports": attempted_target_imports,
        "workingTreeClean": True,
        "passed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "tests" / "online_repositories.json")
    parser.add_argument("--repo", action="append", help="run only a named repository; repeatable")
    parser.add_argument("--cache-dir", type=Path, help="reuse pinned Git checkouts")
    parser.add_argument("--offline", action="store_true", help="do not fetch missing revisions")
    parser.add_argument("--report", type=Path, help="write the JSON result to this path")
    parser.add_argument('--worker-spec', help=argparse.SUPPRESS)
    parser.add_argument('--worker-target', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_spec:
        print(json.dumps(validate_repository(json.loads(args.worker_spec), args.worker_target)))
        return 0

    manifest = json.loads(args.manifest.read_text())
    selected = set(args.repo or ())
    specs = [item for item in manifest["repositories"] if not selected or item["name"] in selected]
    unknown = selected - {item["name"] for item in specs}
    require(not unknown, f"unknown repositories: {', '.join(sorted(unknown))}")
    require(bool(specs), "no repositories selected")

    temporary = None
    if args.cache_dir:
        cache = args.cache_dir.expanduser().resolve()
        cache.mkdir(parents=True, exist_ok=True)
    else:
        temporary = tempfile.TemporaryDirectory(prefix="threadline-online-")
        cache = Path(temporary.name)

    results: list[dict[str, Any]] = []
    failures = 0
    try:
        for spec in specs:
            target = cache / spec["name"]
            try:
                checkout(spec, target, args.offline)
                worker = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                         '--worker-spec', json.dumps(spec), '--worker-target', str(target)],
                                        text=True, capture_output=True, timeout=120)
                require(worker.returncode == 0, worker.stderr.strip()[-4000:] or 'Validation worker failed')
                result = json.loads(worker.stdout)
                print(f"PASS {spec['name']}: {result['parsedFiles']} files, "
                      f"{result['workflowStages']} workflow stages, "
                      f"{result['evidenceChecks']} evidence checks")
            except Exception as exc:
                failures += 1
                result = {"name": spec["name"], "url": spec["url"],
                          "revision": spec["revision"], "passed": False,
                          "error": f"{type(exc).__name__}: {exc}"}
                print(f"FAIL {spec['name']}: {result['error']}", file=sys.stderr)
            results.append(result)
    finally:
        if temporary is not None:
            temporary.cleanup()

    report = {
        "schemaVersion": manifest["schemaVersion"],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "safety": "Targets were cloned and parsed as source; they were not installed, imported, or executed.",
        "passed": failures == 0,
        "repositories": results,
    }
    rendered = json.dumps(report, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered)
        print(f"Report: {args.report.resolve()}")
    else:
        print(rendered)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
