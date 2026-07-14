#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "fleet_wave.py"


def executable(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


class FleetWaveCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.log = self.root / "calls.jsonl"
        self.bd = executable(self.root / "bd", """
import json, os, sys
with open(os.environ['CALL_LOG'], 'a') as f: f.write(json.dumps(['bd', *sys.argv[1:]])+'\\n')
if os.environ.get('BD_FAIL') == '1': raise SystemExit(9)
print(json.dumps({'id': sys.argv[2] if len(sys.argv)>2 else 'x', 'status': os.environ.get('BD_STATUS', 'in_progress'), 'assignee': os.environ.get('BD_ASSIGNEE', 'fleet')}))
""")
        self.ringer = executable(self.root / "ringer", """
import json, os, sys
with open(os.environ['CALL_LOG'], 'a') as f: f.write(json.dumps(['ringer', *sys.argv[1:]])+'\\n')
raise SystemExit(0)
""")
        self.paperclip = executable(self.root / "paperclip", """
import json, os, sys
with open(os.environ['CALL_LOG'], 'a') as f: f.write(json.dumps(['paperclip', *sys.argv[1:]])+'\\n')
""")
        self.ringer_manifest = self.root / "ringer.json"
        self.work = self.root / "work"
        (self.work / "alpha").mkdir(parents=True)
        (self.work / "alpha" / "proof.txt").write_text("proof\n")
        self.ringer_manifest.write_text(json.dumps({
            "run_name": "wave", "workdir": str(self.work),
            "tasks": [{"key": "alpha", "check": "test -s proof.txt", "expect_files": ["proof.txt"]}]
        }))
        self.manifest = self.root / "manifest-v1.json"
        self.write_manifest()
        self.prepared = self.root / "prepared.json"
        self.post = self.root / "post.json"

    def tearDown(self) -> None: self.tmp.cleanup()

    def write_manifest(self, **updates) -> None:
        data = {
            "schema_version": "fleet-wave.v1", "manifest_version": 1, "wave_id": "wave-test",
            "supersedes": None, "ringer_manifest": str(self.ringer_manifest),
            "beads": {"claim_id": "bead-new", "existing_ids": ["bead-old"]},
            "paperclip": {"issue_id": "pc-new", "existing_ids": ["pc-old"]},
            "tasks": [{"key": "alpha", "work_type": "other", "evidence": {"strength": "strong", "kind": "objective"}}]
        }
        data.update(updates)
        self.manifest.write_text(json.dumps(data))

    def run_cli(self, command: str, extra=None, env=None):
        args = [sys.executable, str(TOOL), command, str(self.manifest),
                "--bd-bin", str(self.bd), "--ringer-bin", str(self.ringer),
                "--paperclip-bin", str(self.paperclip)]
        if command == "prepare": args += ["--receipt", str(self.prepared)]
        else: args += ["--prepared-receipt", str(self.prepared), "--run-state", str(self.root/'run.json'), "--receipt", str(self.post)]
        args += extra or []
        e = os.environ.copy(); e["CALL_LOG"] = str(self.log); e.update(env or {})
        return subprocess.run(args, text=True, capture_output=True, env=e)

    def calls(self):
        return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_prepare_claims_reads_back_reconciles_lints_then_dry_runs_and_hashes(self):
        result = self.run_cli("prepare")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertLess(calls.index(["bd", "update", "bead-new", "--claim", "--json"]), calls.index(["bd", "show", "bead-new", "--json"]))
        self.assertIn(["bd", "show", "bead-old", "--json"], calls)
        self.assertIn(["paperclip", "show", "pc-new"], calls)
        self.assertIn(["paperclip", "show", "pc-old"], calls)
        lint = ["ringer", "lint", str(self.ringer_manifest)]
        dry = ["ringer", "run", str(self.ringer_manifest), "--dry-run"]
        self.assertLess(calls.index(lint), calls.index(dry))
        receipt = json.loads(self.prepared.read_text())
        self.assertEqual(receipt["event"], "prepared")
        self.assertRegex(receipt["manifest_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(receipt["ringer_manifest_sha256"], r"^[0-9a-f]{64}$")

    def test_prepare_rejects_bad_version_supersedes_and_weak_evidence_before_commands(self):
        self.write_manifest(manifest_version=2, supersedes=None)
        result = self.run_cli("prepare")
        self.assertNotEqual(result.returncode, 0); self.assertFalse(self.log.exists())
        self.write_manifest(tasks=[{"key": "alpha", "work_type": "other", "evidence": {"strength": "weak", "kind": "objective"}}])
        result = self.run_cli("prepare")
        self.assertNotEqual(result.returncode, 0); self.assertFalse(self.log.exists())

    def test_prepare_rejects_unconfirmed_claim_and_weak_code_check(self):
        result = self.run_cli("prepare", env={"BD_STATUS": "open"})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("ringer", [c[0] for c in self.calls()])
        self.log.unlink()
        self.write_manifest(tasks=[{"key": "alpha", "work_type": "code", "evidence": {"strength": "strong", "kind": "objective"}}])
        result = self.run_cli("prepare")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())

    def test_prepare_degraded_mode_is_explicit_and_never_dispatches(self):
        result = self.run_cli("prepare", ["--degraded-no-dispatch"], {"BD_FAIL": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ringer", [c[0] for c in self.calls()])
        self.assertTrue(json.loads(self.prepared.read_text())["degraded_no_dispatch"])

    def prepare_ok(self):
        result = self.run_cli("prepare")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.log.unlink()
        (self.root / "run.json").write_text(json.dumps({"run_id": "r1", "verdict": "pass", "tasks": [{"key": "alpha", "verdict": "pass"}]}))

    def test_post_run_replays_checks_and_reconciles_beads_before_paperclip(self):
        self.prepare_ok()
        result = self.run_cli("post-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        bead_update = next(i for i,c in enumerate(calls) if c[:3] == ["bd", "comments", "add"])
        pc_update = next(i for i,c in enumerate(calls) if c[:2] == ["paperclip", "comment"])
        self.assertLess(bead_update, pc_update)
        receipt = json.loads(self.post.read_text())
        self.assertEqual(receipt["event"], "post-run")
        self.assertEqual(receipt["ringer_verdict"], "pass")
        self.assertTrue(receipt["independent_replay"]["alpha"])

    def test_post_run_stops_before_paperclip_when_beads_fails(self):
        self.prepare_ok()
        result = self.run_cli("post-run", env={"BD_FAIL": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("paperclip", [c[0] for c in self.calls()])

    def test_judgmental_task_requires_fresh_hash_bound_judge_receipt(self):
        self.write_manifest(tasks=[{"key": "alpha", "work_type": "other", "evidence": {"strength": "strong", "kind": "judgmental"}}])
        self.prepare_ok()
        result = self.run_cli("post-run")
        self.assertNotEqual(result.returncode, 0)
        judge = self.root / "judge.json"
        judge.write_text(json.dumps({"wave_id": "wave-test", "manifest_sha256": json.loads(self.prepared.read_text())["manifest_sha256"], "verdict": "pass", "judged_at": "2999-01-01T00:00:00Z"}))
        result = self.run_cli("post-run", ["--judge-receipt", str(judge)])
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__": unittest.main()
