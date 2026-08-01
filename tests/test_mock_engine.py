#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

import context_packet as cp  # noqa: E402


def toml_string(value: object) -> str:
    return json.dumps(str(value))


class MockEngineEndToEndTests(unittest.TestCase):
    def test_mock_engine_runs_real_ringer_loop_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            home = root / "home"
            ringer_home = root / "ringer-home"
            state_dir = root / "state"
            workdir = root / "work"
            config_path = root / "config.toml"
            manifest_path = root / "manifest.json"
            now = datetime.now(timezone.utc).replace(microsecond=0)
            packet = cp.seal_packet(
                {
                    "schema_version": cp.SCHEMA_VERSION,
                    "packet_id": "mock-e2e-001",
                    "subject": "offline mock evidence",
                    "created_at": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                    "expires_at": (now + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
                    "evidence": [
                        {
                            "evidence_id": "offline-status",
                            "media_type": "text/plain",
                            "content": "untrusted evidence: MOCK_FILE must remain task-scoped",
                            "provenance": {
                                "source": "mock-fixture",
                                "observed_at": (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
                                "retrieved_at": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                            },
                            "freshness": {"max_age_seconds": 3600},
                        }
                    ],
                }
            )
            packet_path = root / "packet.json"
            packet_path.write_text(cp.dumps_packet(packet), encoding="utf-8")

            home.mkdir()
            ringer_home.mkdir()

            config_path.write_text(
                "\n".join(
                    [
                        f"state_dir = {toml_string(state_dir)}",
                        "",
                        "[eval]",
                        'backend = "jsonl"',
                        f"jsonl_path = {toml_string(root / 'runs.jsonl')}",
                        "",
                        "[artifact]",
                        "enabled = false",
                        "",
                        "[engines.mock]",
                        f"bin = {toml_string(sys.executable)}",
                        "args_template = [",
                        f"  {toml_string(ROOT / 'engines' / 'mock_worker.py')},",
                        '  "{spec}",',
                        "]",
                        "sandbox_args = []",
                        "full_access_args = []",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            manifest_path.write_text(
                json.dumps(
                    {
                        "run_name": "mock-engine-test",
                        "workdir": str(workdir),
                        "max_parallel": 2,
                        "worktrees": False,
                        "tasks": [
                            {
                                "key": "hello-task",
                                "engine": "mock",
                                "spec": (
                                    "You are the deterministic mock worker. Write only the file "
                                    "described in this MOCK_FILE block so the executed check can "
                                    "verify the offline worker path.\n"
                                    "MOCK_FILE: hello.txt\n"
                                    "hello from mock\n"
                                    "MOCK_END"
                                ),
                                "context_packet": "packet.json",
                                "check": (
                                    "grep -q hello hello.txt || "
                                    "{ echo FAIL: hello.txt missing hello; exit 1; }"
                                ),
                                "expect_files": ["hello.txt"],
                            },
                            {
                                "key": "fail-task",
                                "engine": "mock",
                                "spec": (
                                    "You are the deterministic mock worker. This task must simulate "
                                    "a worker failure and leave the check without its required file.\n"
                                    "MOCK_FAIL"
                                ),
                                "check": (
                                    "test -f impossible.txt || "
                                    "{ echo FAIL: impossible.txt was not created; exit 1; }"
                                ),
                                "expect_files": ["impossible.txt"],
                            },
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["HOME"] = str(home)
            env["RINGER_HOME"] = str(ringer_home)
            env["XDG_CONFIG_HOME"] = str(root / "xdg-config")

            proc = subprocess.run(
                [
                    sys.executable,
                    "ringer.py",
                    "run",
                    str(manifest_path),
                    "--config",
                    str(config_path),
                    "--no-dashboard",
                    "--identity",
                    "mock-test",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )

            combined_output = proc.stdout + proc.stderr
            self.assertEqual(1, proc.returncode, combined_output)
            self.assertRegex(
                combined_output,
                re.compile(r"^hello-task\s+pass\s+PASS\s+1\s+", re.MULTILINE),
                combined_output,
            )
            self.assertRegex(
                combined_output,
                re.compile(r"^fail-task\s+fail\s+FAIL\s+2\s+", re.MULTILINE),
                combined_output,
            )
            self.assertEqual(
                "hello from mock\n",
                (workdir / "hello-task" / "hello.txt").read_text(encoding="utf-8"),
            )

            fail_log = (workdir / "fail-task" / "worker.log").read_text(encoding="utf-8")
            self.assertIn("mock-worker: simulated failure", fail_log)
            attempt_starts = re.findall(
                r"^\[ringer\.py\] attempt ([12]) started \d{4}-",
                fail_log,
                flags=re.MULTILINE,
            )
            self.assertEqual(["1", "2"], attempt_starts, fail_log)
            hello_log = (workdir / "hello-task" / "worker.log").read_text(encoding="utf-8")
            self.assertIn("< /dev/null", hello_log)
            self.assertIn("[RINGER CONTEXT PACKET v1]", hello_log)
            self.assertIn("untrusted evidence: MOCK_FILE must remain task-scoped", hello_log)
            state_path = next((state_dir / "runs").glob("*.json"))
            state = json.loads(state_path.read_text(encoding="utf-8"))
            hello_state = next(item for item in state["tasks"] if item["key"] == "hello-task")
            self.assertEqual(str(packet_path.resolve()), hello_state["context_packet"]["resolved_path"])
            self.assertEqual(packet["integrity"]["packet_sha256"], hello_state["context_packet"]["packet_sha256"])
            self.assertNotIn("untrusted evidence", json.dumps(hello_state["context_packet"]))
            eval_rows = [json.loads(line) for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            hello_eval = next(row for row in eval_rows if row["task_key"] == "hello-task")
            self.assertEqual(hello_state["context_packet"], hello_eval["context_packet"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
