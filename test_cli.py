"""The agent CLI must disclose partial analysis and keep evidence snapshot-pinned."""
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from threadline.cli import main


class CLIQueryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "app.py").write_text(
            "def helper(value):\n"
            "    return value\n\n"
            "def entry(value):\n"
            "    if value:\n"
            "        return helper(value)\n"
            "    return 0\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def query(self, *arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(list(arguments))
        return status, json.loads(output.getvalue())

    def test_initial_query_discloses_parse_failure_and_strict_mode(self):
        (self.root / "broken.py").write_text("def unfinished(:\n", encoding="utf-8")
        status, result = self.query("inspect", str(self.root), "--query", "entry")
        self.assertEqual(status, 0)
        self.assertEqual(result["schemaVersion"], result["result"].get("schemaVersion", result["schemaVersion"]))
        self.assertFalse(result["analysis"]["complete"])
        self.assertEqual(result["analysis"]["parseErrors"], 1)
        self.assertEqual(result["analysis"]["skippedFiles"], 1)
        self.assertEqual(result["result"]["symbols"]["total"], 1)

        strict_status, strict = self.query(
            "inspect", str(self.root), "--query", "entry", "--strict-complete",
        )
        self.assertEqual(strict_status, 3)
        self.assertEqual(strict["analysis"]["parseErrors"], 1)
        self.assertEqual(strict["analysis"]["analysisErrors"], 1)
        self.assertEqual(strict["analysis"]["configurationErrors"], 0)
        _, diagnostics = self.query(
            "diagnostics", str(self.root), "--category", "errors",
        )
        self.assertEqual(diagnostics["result"]["rows"]["items"][0]["file"], "broken.py")

    def test_configuration_read_failure_is_distinct_from_python_parse_error(self):
        (self.root / "pyproject.toml").write_bytes(b"\xff")
        status, result = self.query("summary", str(self.root))
        self.assertEqual(status, 0)
        self.assertFalse(result["analysis"]["complete"])
        self.assertEqual(result["analysis"]["analysisErrors"], 1)
        self.assertEqual(result["analysis"]["configurationErrors"], 1)
        self.assertEqual(result["analysis"]["parseErrors"], 0)
        diagnostics_status, diagnostics = self.query(
            "diagnostics", str(self.root), "--category", "errors",
        )
        self.assertEqual(diagnostics_status, 0)
        issue = diagnostics["result"]["rows"]["items"][0]
        self.assertEqual(issue["file"], "pyproject.toml")
        self.assertEqual(issue["kind"], "configuration")

    def test_saved_snapshot_keeps_source_and_rejects_mismatched_continuation(self):
        artifact = self.root / "review.json"
        status, saved = self.query("snapshot", str(self.root), "--output", str(artifact))
        self.assertEqual(status, 0)
        snapshot_id = saved["snapshotId"]

        status, symbols = self.query(
            "symbols", "--session", str(artifact), "--snapshot", snapshot_id,
            "--query", "entry", "--compact",
        )
        self.assertEqual(status, 0)
        evidence = symbols["result"]["symbols"]["items"][0]["evidenceId"]
        _, method = self.query(
            "method", "--session", str(artifact), "--snapshot", snapshot_id,
            "--symbol", "entry",
        )
        self.assertEqual(method["result"]["name"], "entry")
        self.assertTrue(method["result"]["operations"]["items"])

        _, workflow = self.query(
            "workflow", "--session", str(artifact), "--snapshot", snapshot_id,
            "--entrypoint", "entry", "--detail", "references", "--compact",
        )
        call = next(stage for stage in workflow["result"]["stages"]["items"] if stage.get("evidence"))
        self.assertEqual(workflow["detail"], "references")
        self.assertEqual(call["evidence"][0]["label"], "Original call site")
        self.assertIn("scope", call["evidence"][0])
        _, call_source = self.query(
            "source", "--session", str(artifact), "--snapshot", snapshot_id,
            "--evidence", call["evidence"][0]["evidenceId"],
        )
        self.assertIn("helper(value)", call_source["result"]["source"])

        (self.root / "app.py").write_text("def entry(value):\n    return 99\n", encoding="utf-8")
        _, source = self.query(
            "source", "--session", str(artifact), "--snapshot", snapshot_id,
            "--evidence", evidence,
        )
        self.assertIn("return helper(value)", source["result"]["source"])
        self.assertNotIn("return 99", source["result"]["source"])

        mismatch_status, mismatch = self.query(
            "symbols", "--session", str(artifact), "--snapshot", "wrong",
        )
        self.assertEqual(mismatch_status, 2)
        self.assertEqual(mismatch["error"]["code"], "query_error")
        self.assertIn("snapshot mismatch", mismatch["error"]["message"])

    def test_reference_detail_preserves_event_proof_roles_and_source(self):
        (self.root / "app.py").write_text(
            "def callback(payload):\n"
            "    return payload\n\n"
            "def register(bus):\n"
            "    bus.subscribe('ready', callback)\n\n"
            "def emit(bus):\n"
            "    bus.publish('ready', {'id': 1})\n",
            encoding="utf-8",
        )
        artifact = self.root / "event-review.json"
        self.query("snapshot", str(self.root), "--output", str(artifact))
        status, workflow = self.query(
            "workflow", "--session", str(artifact), "--entrypoint", "emit",
            "--detail", "references", "--compact",
        )
        self.assertEqual(status, 0)
        event_stage = next(
            stage for stage in workflow["result"]["stages"]["items"]
            if stage["id"].startswith("event:")
        )
        self.assertEqual(event_stage["status"], "possible")
        proofs = event_stage["evidence"]
        self.assertEqual(
            [proof["label"] for proof in proofs],
            ["Event publication", "Callback registration"],
        )
        self.assertTrue(all(proof.get("scope") and proof.get("evidenceId") for proof in proofs))
        self.assertTrue(all("span" not in proof for proof in proofs))
        for proof, original in zip(proofs, ("publish('ready'", "subscribe('ready'")):
            source_status, source = self.query(
                "source", "--session", str(artifact), "--evidence", proof["evidenceId"],
            )
            self.assertEqual(source_status, 0)
            self.assertIn(original, source["result"]["source"])

    def test_live_continuation_requires_snapshot_and_rejects_source_edit(self):
        _, first = self.query("symbols", str(self.root), "--limit", "1")
        cursor = first["result"]["symbols"]["nextCursor"]
        self.assertEqual(cursor, 1)
        first_snapshot = first["snapshotId"]
        evidence = first["result"]["symbols"]["items"][0]["evidenceId"]

        unpinned_status, unpinned = self.query(
            "symbols", str(self.root), "--limit", "1", "--cursor", str(cursor),
        )
        self.assertEqual(unpinned_status, 2)
        self.assertIn("--snapshot is required", unpinned["error"]["message"])

        _, first_source = self.query(
            "source", str(self.root), "--file", "app.py", "--start", "1", "--end", "2",
        )
        source_page_status, source_page_error = self.query(
            "source", str(self.root), "--file", "app.py", "--start", "3",
        )
        self.assertEqual(source_page_status, 2)
        self.assertIn("--snapshot is required", source_page_error["error"]["message"])
        _, next_source = self.query(
            "source", str(self.root), "--file", "app.py", "--start", "3",
            "--snapshot", first_source["snapshotId"],
        )
        self.assertIn("def entry", next_source["result"]["source"])

        (self.root / "app.py").write_text(
            (self.root / "app.py").read_text(encoding="utf-8") + "\ndef later():\n    return 9\n",
            encoding="utf-8",
        )
        changed_status, changed = self.query(
            "symbols", str(self.root), "--limit", "1", "--cursor", str(cursor),
            "--snapshot", first_snapshot,
        )
        self.assertEqual(changed_status, 2)
        self.assertIn("snapshot mismatch", changed["error"]["message"])
        stale_evidence_status, stale_evidence = self.query(
            "source", str(self.root), "--evidence", evidence,
            "--snapshot", first_snapshot,
        )
        self.assertEqual(stale_evidence_status, 2)
        self.assertIn("snapshot mismatch", stale_evidence["error"]["message"])
        stale_source_status, stale_source = self.query(
            "source", str(self.root), "--file", "app.py", "--start", "3",
            "--snapshot", first_source["snapshotId"],
        )
        self.assertEqual(stale_source_status, 2)
        self.assertIn("snapshot mismatch", stale_source["error"]["message"])

        change_page_status, change_page_error = self.query(
            "changes", str(self.root), "--cursor", "1", "--snapshot", first_snapshot,
        )
        self.assertEqual(change_page_status, 2)
        self.assertIn("--session is required", change_page_error["error"]["message"])

        artifact = self.root / "frozen.json"
        self.query("snapshot", str(self.root), "--output", str(artifact))
        _, saved_first = self.query("symbols", "--session", str(artifact), "--limit", "1")
        saved_cursor = saved_first["result"]["symbols"]["nextCursor"]
        _, saved_second = self.query(
            "symbols", "--session", str(artifact), "--limit", "1",
            "--cursor", str(saved_cursor),
        )
        self.assertEqual(saved_first["snapshotId"], saved_second["snapshotId"])

    def test_structured_argument_error_and_paged_branch(self):
        with self.assertRaises(SystemExit) as exit_status:
            self.query("source", str(self.root), "--start", "not-an-int")
        self.assertEqual(exit_status.exception.code, 2)

        _, scope = self.query("scope", str(self.root), "--symbol", "entry")
        branch = next(
            operation for operation in scope["result"]["flow"]["items"]
            if operation["kind"] == "If"
        )
        unpinned_status, unpinned = self.query(
            "branch", str(self.root), "--symbol", "entry",
            "--operation", branch["id"], "--arm", "0",
        )
        self.assertEqual(unpinned_status, 2)
        self.assertIn("--snapshot is required", unpinned["error"]["message"])
        status, body = self.query(
            "branch", str(self.root), "--symbol", "entry",
            "--operation", branch["id"], "--arm", "0", "--limit", "1",
            "--snapshot", scope["snapshotId"],
        )
        self.assertEqual(status, 0)
        self.assertEqual(body["result"]["flow"]["total"], 1)
        self.assertEqual(body["pagination"]["flow"]["nextCursor"], None)

        _, symbol = self.query("symbols", str(self.root), "--query", "entry")
        symbol_id = symbol["result"]["symbols"]["items"][0]["id"]
        id_status, id_error = self.query("method", str(self.root), "--symbol", symbol_id)
        self.assertEqual(id_status, 2)
        self.assertIn("--snapshot is required", id_error["error"]["message"])
        _, method = self.query("method", str(self.root), "--symbol", "entry")
        self.assertEqual(method["result"]["name"], "entry")

        evidence = symbol["result"]["symbols"]["items"][0]["evidenceId"]
        source_status, source_error = self.query("source", str(self.root), "--evidence", evidence)
        self.assertEqual(source_status, 2)
        self.assertIn("--snapshot is required", source_error["error"]["message"])
        _, source = self.query(
            "source", str(self.root), "--evidence", evidence,
            "--snapshot", symbol["snapshotId"],
        )
        self.assertIn("def entry", source["result"]["source"])

    def test_saved_change_snapshot_pages_file_edits_and_both_sides_evidence(self):
        source = self.root / "app.py"
        source.write_text(
            "FEE = 1\n\ndef total(value):\n    return value * FEE\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "app.py"], check=True)
        subprocess.run([
            "git", "-C", str(self.root), "-c", "user.name=Threadline",
            "-c", "user.email=threadline@example.invalid", "commit", "-qm", "baseline",
        ], check=True)
        source.write_text(
            "FEE = 2\n\ndef total(value):\n    return value * FEE\n",
            encoding="utf-8",
        )
        artifact = self.root / "changes.json"
        status, saved = self.query(
            "snapshot", str(self.root), "--base", "HEAD", "--output", str(artifact),
        )
        self.assertEqual(status, 0)
        self.assertTrue(saved["result"]["hasChanges"])

        _, files = self.query(
            "changes", "--session", str(artifact), "--category", "files", "--limit", "1",
        )
        self.assertEqual(files["result"]["records"]["total"], 1)
        self.assertEqual(files["result"]["records"]["items"][0]["path"], "app.py")
        _, outside = self.query(
            "changes", "--session", str(artifact), "--category", "unassessedChanges",
        )
        self.assertGreater(outside["result"]["records"]["total"], 0)
        self.assertEqual(outside["result"]["counts"]["changedMethods"], 0)
        snapshot_by_side = {
            "working": outside["result"]["workingSnapshotId"],
            "base": outside["result"]["baseSnapshotId"],
        }
        source.write_text("FEE = 3\n", encoding="utf-8")
        seen = set()
        for row in outside["result"]["records"]["items"]:
            if not row.get("evidenceId"):
                continue
            _, evidence = self.query(
                "source", "--session", str(artifact),
                "--snapshot", snapshot_by_side[row["side"]],
                "--evidence", row["evidenceId"],
            )
            seen.add(row["side"])
            self.assertIn("FEE = 1" if row["side"] == "base" else "FEE = 2", evidence["result"]["source"])
            self.assertNotIn("FEE = 3", evidence["result"]["source"])
        self.assertEqual(seen, {"base", "working"})


if __name__ == "__main__":
    unittest.main()
