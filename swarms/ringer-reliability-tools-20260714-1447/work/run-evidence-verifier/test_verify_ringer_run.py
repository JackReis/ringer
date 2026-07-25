"""Tests for the Ringer run verifier CLI and core validation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import verify_ringer_run


SCRIPT = Path(__file__).with_name("verify_ringer_run.py")


class VerifyRingerRunTests(unittest.TestCase):
    """Validate success, failure, determinism, and redaction behavior."""

    def write_json(self, path: Path, value: dict[str, Any]) -> None:
        """Write fixture JSON."""

        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

    def write_jsonl(self, path: Path, rows: list[dict[str, Any]]) -> None:
        """Write fixture JSONL."""

        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )

    def base_state(self, *, tasks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Return a minimal valid state fixture."""

        return {
            "finished": True,
            "run_id": "run-001",
            "state": "finished",
            "summary": {"fail": 0, "pass": 1},
            "tasks": tasks
            if tasks is not None
            else [
                {
                    "attempts": 1,
                    "check_returncode": 0,
                    "check_timed_out": False,
                    "key": "task-a",
                    "status": "pass",
                    "verdict": "PASS",
                }
            ],
        }

    def base_eval(self, task_key: str = "task-a") -> list[dict[str, Any]]:
        """Return a minimal valid eval-log fixture."""

        return [
            {
                "run_id": "run-001",
                "task_key": task_key,
                "verdict": "PASS",
                "verify_method": "executed-check",
            }
        ]

    def run_cli(
        self,
        tmp: Path,
        state: dict[str, Any],
        rows: list[dict[str, Any]] | None,
        *,
        require_deliverables: bool = False,
        eval_text: str | None = None,
        output: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, Any], str]:
        """Run the verifier subprocess and return process, parsed output, and raw text."""

        state_path = tmp / "state.json"
        eval_path = tmp / "eval.jsonl"
        output_path = output or (tmp / "out.json")
        self.write_json(state_path, state)
        if eval_text is not None:
            eval_path.write_text(eval_text, encoding="utf-8")
        else:
            self.write_jsonl(eval_path, rows if rows is not None else self.base_eval())

        args = [
            sys.executable,
            str(SCRIPT),
            "--state",
            str(state_path),
            "--eval-log",
            str(eval_path),
            "--output",
            str(output_path),
        ]
        if require_deliverables:
            args.append("--require-deliverables")
        proc = subprocess.run(args, text=True, capture_output=True, check=False)
        raw = output_path.read_text(encoding="utf-8")
        return proc, json.loads(raw), raw

    def error_codes(self, report: dict[str, Any]) -> set[str]:
        """Return all error codes from a verifier report."""

        return {str(item["code"]) for item in report["errors"]}

    def test_clean_run_cli_and_core(self) -> None:
        """A fully passing run exits zero and is valid through CLI and core API."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            state = self.base_state()
            rows = self.base_eval()
            proc, report, _ = self.run_cli(tmp, state, rows)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(report["valid"])
            self.assertEqual(report["errors"], [])
            self.assertEqual(report["run_id"], "run-001")
            self.assertEqual(report["summary"]["tasks_total"], 1)

            core_report = verify_ringer_run.verify_run(tmp / "state.json", tmp / "eval.jsonl")
            self.assertTrue(core_report["valid"])
            self.assertEqual(core_report["per_task"][0]["key"], "task-a")

    def test_retry_followed_by_pass_counts_retries(self) -> None:
        """Earlier FAIL and TIMEOUT rows are allowed and counted as retries."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            rows = [
                {
                    "run_id": "run-001",
                    "task_key": "task-a",
                    "verdict": "FAIL",
                    "verify_method": "executed-check",
                },
                {
                    "run_id": "run-001",
                    "task_key": "task-a",
                    "verdict": "TIMEOUT",
                    "verify_method": "executed-check",
                },
                {
                    "run_id": "run-001",
                    "task_key": "task-a",
                    "verdict": "PASS",
                    "verify_method": "executed-check",
                },
            ]
            proc, report, _ = self.run_cli(tmp, self.base_state(), rows)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(report["valid"])
            self.assertEqual(report["summary"]["retries_total"], 2)
            self.assertEqual(report["per_task"][0]["retries"], 2)

    def test_shared_eval_log_ignores_unrelated_runs(self) -> None:
        """Rows for other runs in the shared append-only log are ignored."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            unrelated = {
                "run_id": "another-run",
                "task_key": "another-task",
                "verdict": "FAIL",
                "verify_method": "executed-check",
            }
            rows = [unrelated, *self.base_eval(), unrelated]
            proc, report, _ = self.run_cli(tmp, self.base_state(), rows)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(report["valid"])
            self.assertEqual(report["errors"], [])

    def test_unfinished_state_fails(self) -> None:
        """Unfinished state flags make the report invalid."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            state = self.base_state()
            state["finished"] = False
            state["state"] = "running"
            proc, report, _ = self.run_cli(tmp, state, self.base_eval())
            self.assertEqual(proc.returncode, 1)
            self.assertIn("state_finished_not_true", self.error_codes(report))
            self.assertIn("state_state_not_finished", self.error_codes(report))

    def test_nonzero_summary_failure_fails(self) -> None:
        """A nonzero summary.fail count fails validation."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            state = self.base_state()
            state["summary"]["fail"] = 1
            proc, report, _ = self.run_cli(tmp, state, self.base_eval())
            self.assertEqual(proc.returncode, 1)
            self.assertIn("summary_fail_nonzero", self.error_codes(report))

    def test_failed_or_timed_out_task_check_fails(self) -> None:
        """Task check failures and timeouts are reported as task errors."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            state = self.base_state()
            task = state["tasks"][0]
            task["check_returncode"] = 2
            task["check_timed_out"] = True
            task["status"] = "fail"
            task["verdict"] = "FAIL"
            proc, report, _ = self.run_cli(tmp, state, self.base_eval())
            self.assertEqual(proc.returncode, 1)
            codes = self.error_codes(report)
            self.assertIn("task_check_returncode_nonzero", codes)
            self.assertIn("task_check_timed_out", codes)
            self.assertIn("task_status_not_pass", codes)
            self.assertIn("task_verdict_not_pass", codes)

    def test_missing_latest_eval_pass_fails(self) -> None:
        """The latest matching eval row must be a PASS executed-check."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            rows = [
                {
                    "run_id": "run-001",
                    "task_key": "task-a",
                    "verdict": "PASS",
                    "verify_method": "executed-check",
                },
                {
                    "run_id": "run-001",
                    "task_key": "task-a",
                    "verdict": "FAIL",
                    "verify_method": "executed-check",
                },
            ]
            proc, report, _ = self.run_cli(tmp, self.base_state(), rows)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("latest_eval_not_pass", self.error_codes(report))
            self.assertEqual(report["per_task"][0]["latest_eval_line"], 2)

    def test_malformed_jsonl_reports_line_number(self) -> None:
        """Malformed JSONL fails cleanly and identifies the offending line."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            text = (
                json.dumps(self.base_eval()[0])
                + "\n"
                + "{not json}\n"
            )
            proc, report, _ = self.run_cli(
                tmp,
                self.base_state(),
                None,
                eval_text=text,
            )
            self.assertEqual(proc.returncode, 1)
            malformed = [
                item for item in report["errors"] if item["code"] == "eval_jsonl_malformed"
            ]
            self.assertEqual(malformed[0]["line"], 2)

    def test_duplicate_task_keys_fail(self) -> None:
        """Duplicate state task keys are rejected."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            task = {
                "attempts": 1,
                "check_returncode": 0,
                "check_timed_out": False,
                "key": "same",
                "status": "pass",
                "verdict": "PASS",
            }
            state = self.base_state(tasks=[dict(task), dict(task)])
            rows = self.base_eval("same")
            proc, report, _ = self.run_cli(tmp, state, rows)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("duplicate_task_key", self.error_codes(report))

    def test_deliverable_requirement_success_and_failure(self) -> None:
        """Declared deliverables are checked only when requested."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            artifact = tmp / "artifact.txt"
            artifact.write_text("not read by verifier\n", encoding="utf-8")
            task = self.base_state()["tasks"][0]
            task["deliverables"] = ["artifact.txt"]
            state = self.base_state(tasks=[task])
            proc, report, _ = self.run_cli(
                tmp,
                state,
                self.base_eval(),
                require_deliverables=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(report["valid"])
            self.assertEqual(report["summary"]["deliverables_total"], 1)

            artifact.unlink()
            proc, report, _ = self.run_cli(
                tmp,
                state,
                self.base_eval(),
                require_deliverables=True,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("deliverable_missing", self.error_codes(report))

    def test_deterministic_ordering(self) -> None:
        """Output is byte-stable and per-task entries are sorted by key."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            task_b = {
                "attempts": 1,
                "check_returncode": 0,
                "check_timed_out": False,
                "key": "task-b",
                "status": "pass",
                "verdict": "PASS",
            }
            task_a = dict(task_b, key="task-a")
            state = self.base_state(tasks=[task_b, task_a])
            rows = [self.base_eval("task-b")[0], self.base_eval("task-a")[0]]
            first_output = tmp / "first.json"
            second_output = tmp / "second.json"
            proc, report, raw_first = self.run_cli(tmp, state, rows, output=first_output)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            proc, _, raw_second = self.run_cli(tmp, state, rows, output=second_output)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(raw_first, raw_second)
            self.assertEqual([item["key"] for item in report["per_task"]], ["task-a", "task-b"])

    def test_atomic_nested_output(self) -> None:
        """The CLI creates nested output parents and writes valid JSON."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            nested = tmp / "nested" / "deeper" / "report.json"
            proc, report, _ = self.run_cli(
                tmp,
                self.base_state(),
                self.base_eval(),
                output=nested,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(nested.exists())
            self.assertTrue(report["valid"])

    def test_secret_like_fixture_strings_are_redacted(self) -> None:
        """Spec, notes, URLs, environment values, and check output stay out of output."""

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            secret_spec = "sk-test-secret-fixture"
            secret_note = "https://secret.example.invalid/private"
            secret_env = "TOKEN=secret-env-fixture"
            secret_output = "check output includes secret-output-fixture"
            task = self.base_state()["tasks"][0]
            task["spec"] = secret_spec
            task["notes"] = secret_note
            task["environment"] = {"API_TOKEN": secret_env}
            state = self.base_state(tasks=[task])
            rows = [
                {
                    "check_output": secret_output,
                    "run_id": "run-001",
                    "task_key": "task-a",
                    "url": secret_note,
                    "verdict": "PASS",
                    "verify_method": "executed-check",
                }
            ]
            proc, report, raw = self.run_cli(tmp, state, rows)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(report["valid"])
            for secret in (secret_spec, secret_note, secret_env, secret_output):
                self.assertNotIn(secret, raw)

            invalid_status = "sk-status-secret-fixture"
            invalid_method = "https://secret.example.invalid/method"
            task["status"] = invalid_status
            rows[0]["verify_method"] = invalid_method
            proc, report, raw = self.run_cli(tmp, state, rows)
            self.assertEqual(proc.returncode, 1)
            self.assertFalse(report["valid"])
            self.assertNotIn(invalid_status, raw)
            self.assertNotIn(invalid_method, raw)


if __name__ == "__main__":
    unittest.main()
