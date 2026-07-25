"""Tests for the Ringer clean-streak audit utility."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import audit_ringer_streak


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "audit_ringer_streak.py"


class AuditRingerStreakTests(unittest.TestCase):
    """Exercise the CLI and core audit functions with local fixtures only."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.states_dir = self.base / "states"
        self.states_dir.mkdir()
        self.eval_log = self.base / "eval.jsonl"
        self.output = self.base / "audit.json"
        self.prefix = "ringer-clean-"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_state(
        self,
        run_id: str,
        started_at: str,
        *,
        run_name: str | None = None,
        finished: bool = True,
        fail: int = 0,
        tasks: list[dict[str, Any]] | None = None,
        filename: str | None = None,
    ) -> None:
        """Write a minimal state JSON fixture."""
        state = {
            "run_id": run_id,
            "run_name": run_name if run_name is not None else f"{self.prefix}{run_id}",
            "started_at": started_at,
            "finished": finished,
            "summary": {"fail": fail},
            "tasks": tasks if tasks is not None else [self.task("task-1")],
            "spec": "SECRET_SPEC_VALUE",
            "checks": "SECRET_CHECK_VALUE",
            "notes": "SECRET_NOTE_VALUE",
            "log": "SECRET_LOG_VALUE",
            "path": "/tmp/SECRET_PATH",
            "url": "https://secret.example.invalid/token",
            "environment": {"TOKEN": "SECRET_ENV_VALUE"},
        }
        path = self.states_dir / (filename or f"{run_id}.json")
        path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")

    @staticmethod
    def task(
        key: str,
        *,
        verdict: str = "PASS",
        status: str = "pass",
        check_returncode: int = 0,
        check_timed_out: bool = False,
        attempts: int = 1,
    ) -> dict[str, Any]:
        """Return a task fixture with secret-like extra fields."""
        return {
            "task_key": key,
            "verdict": verdict,
            "status": status,
            "check_returncode": check_returncode,
            "check_timed_out": check_timed_out,
            "attempts": attempts,
            "spec": "SECRET_TASK_SPEC",
            "checks": "SECRET_TASK_CHECKS",
            "notes": "SECRET_TASK_NOTES",
            "log": "SECRET_TASK_LOG",
        }

    def write_eval(self, rows: list[dict[str, Any]]) -> None:
        """Write eval JSONL rows."""
        text = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
        self.eval_log.write_text(text, encoding="utf-8")

    def eval_row(
        self,
        run_id: str,
        task_key: str = "task-1",
        *,
        verdict: str = "PASS",
        retry: bool = False,
    ) -> dict[str, Any]:
        """Return one eval-row fixture."""
        return {
            "run_id": run_id,
            "task_key": task_key,
            "verdict": verdict,
            "retry": retry,
            "notes": "SECRET_EVAL_NOTE",
            "url": "https://secret.example.invalid/eval",
        }

    def run_cli(
        self,
        *,
        required_count: int,
        prefix: str | None = None,
        output: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run the CLI under subprocess."""
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        cmd = [
            sys.executable,
            "-B",
            str(SCRIPT),
            "--states-dir",
            str(self.states_dir),
            "--eval-log",
            str(self.eval_log),
            "--run-prefix",
            self.prefix if prefix is None else prefix,
            "--required-count",
            str(required_count),
            "--output",
            str(self.output if output is None else output),
        ]
        return subprocess.run(cmd, text=True, capture_output=True, env=env, check=False)

    def read_output(self, output: Path | None = None) -> dict[str, Any]:
        """Read the CLI JSON output."""
        return json.loads((self.output if output is None else output).read_text(encoding="utf-8"))

    def test_exact_clean_streak_exits_zero(self) -> None:
        self.write_state("run-1", "2026-07-14T10:00:00Z")
        self.write_state("run-2", "2026-07-14T11:00:00Z")
        self.write_eval([self.eval_row("run-1"), self.eval_row("run-2")])

        result = self.run_cli(required_count=2)
        data = self.read_output()
        core = audit_ringer_streak.audit(self.states_dir, self.eval_log, self.prefix, 2)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(data["valid"])
        self.assertEqual(data["required_count"], 2)
        self.assertEqual(data["selected_count"], 2)
        self.assertEqual(data["clean_count"], 2)
        self.assertEqual(data["errors"], [])
        self.assertEqual([run["run_id"] for run in data["runs"]], ["run-1", "run-2"])
        self.assertEqual(core, data)

    def test_insufficient_runs_fails(self) -> None:
        self.write_state("run-1", "2026-07-14T10:00:00Z")
        self.write_eval([self.eval_row("run-1")])

        result = self.run_cli(required_count=2)
        data = self.read_output()

        self.assertEqual(result.returncode, 1)
        self.assertFalse(data["valid"])
        self.assertEqual(data["selected_count"], 1)
        self.assertIn("insufficient_runs", data["errors"])

    def test_failure_in_latest_window_fails(self) -> None:
        self.write_state("run-1", "2026-07-14T09:00:00Z")
        self.write_state(
            "run-2",
            "2026-07-14T10:00:00Z",
            fail=1,
            tasks=[self.task("task-1", verdict="FAIL", status="fail", check_returncode=1)],
        )
        self.write_state("run-3", "2026-07-14T11:00:00Z")
        self.write_eval([self.eval_row("run-1"), self.eval_row("run-2"), self.eval_row("run-3")])

        result = self.run_cli(required_count=2)
        data = self.read_output()

        self.assertEqual(result.returncode, 1)
        self.assertFalse(data["valid"])
        latest = {run["run_id"]: run for run in data["runs"][-2:]}
        self.assertFalse(latest["run-2"]["clean"])
        self.assertIn("summary_fail_nonzero", latest["run-2"]["reasons"])

    def test_retry_eval_invalidates_run(self) -> None:
        self.write_state("run-1", "2026-07-14T10:00:00Z")
        self.write_eval([self.eval_row("run-1", retry=False), self.eval_row("run-1", retry=True)])

        result = self.run_cli(required_count=1)
        data = self.read_output()

        self.assertEqual(result.returncode, 1)
        self.assertFalse(data["runs"][0]["clean"])
        self.assertIn("eval_retry_true", data["runs"][0]["reasons"])

    def test_earlier_failure_outside_latest_window_does_not_affect_acceptance(self) -> None:
        self.write_state(
            "run-1",
            "2026-07-14T09:00:00Z",
            fail=1,
            tasks=[self.task("task-1", verdict="FAIL", status="fail", check_returncode=1)],
        )
        self.write_state("run-2", "2026-07-14T10:00:00Z")
        self.write_state("run-3", "2026-07-14T11:00:00Z")
        self.write_eval([self.eval_row("run-1"), self.eval_row("run-2"), self.eval_row("run-3")])

        result = self.run_cli(required_count=2)
        data = self.read_output()

        self.assertEqual(result.returncode, 0, data)
        self.assertTrue(data["valid"])
        self.assertEqual(data["errors"], [])
        self.assertFalse(data["runs"][0]["clean"])
        self.assertEqual(data["clean_count"], 2)

    def test_sort_order_is_started_at_then_run_id(self) -> None:
        self.write_state("run-b", "2026-07-14T10:00:00Z")
        self.write_state("run-a", "2026-07-14T10:00:00Z")
        self.write_state("run-0", "2026-07-14T09:00:00Z")
        self.write_eval([self.eval_row("run-b"), self.eval_row("run-a"), self.eval_row("run-0")])

        result = self.run_cli(required_count=3)
        data = self.read_output()

        self.assertEqual(result.returncode, 0)
        self.assertEqual([run["run_id"] for run in data["runs"]], ["run-0", "run-a", "run-b"])

    def test_duplicate_run_ids_fail(self) -> None:
        self.write_state("run-1", "2026-07-14T10:00:00Z", filename="a.json")
        self.write_state("run-1", "2026-07-14T11:00:00Z", filename="b.json")
        self.write_eval([self.eval_row("run-1")])

        result = self.run_cli(required_count=1)
        data = self.read_output()

        self.assertEqual(result.returncode, 1)
        self.assertIn("duplicate_run_id", data["errors"])
        self.assertNotIn("Traceback", result.stderr)

    def test_duplicate_task_keys_fail(self) -> None:
        self.write_state(
            "run-1",
            "2026-07-14T10:00:00Z",
            tasks=[self.task("task-1"), self.task("task-1")],
        )
        self.write_eval([self.eval_row("run-1")])

        result = self.run_cli(required_count=1)
        data = self.read_output()

        self.assertEqual(result.returncode, 1)
        self.assertIn("duplicate_task_key", data["errors"])
        self.assertIn("duplicate_task_key", data["runs"][0]["reasons"])

    def test_malformed_timestamps_fail(self) -> None:
        self.write_state("run-1", "not-a-timestamp")
        self.write_eval([self.eval_row("run-1")])

        result = self.run_cli(required_count=1)
        data = self.read_output()

        self.assertEqual(result.returncode, 1)
        self.assertIn("malformed_timestamp", data["errors"])

    def test_missing_eval_rows_fail(self) -> None:
        self.write_state("run-1", "2026-07-14T10:00:00Z")
        self.write_eval([])

        result = self.run_cli(required_count=1)
        data = self.read_output()

        self.assertEqual(result.returncode, 1)
        self.assertIn("missing_eval_row", data["errors"])
        self.assertIn("eval_missing", data["runs"][0]["reasons"])

    def test_wrong_prefix_selects_no_runs(self) -> None:
        self.write_state("run-1", "2026-07-14T10:00:00Z", run_name="other-run-1")
        self.write_eval([self.eval_row("run-1")])

        result = self.run_cli(required_count=1, prefix=self.prefix)
        data = self.read_output()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(data["selected_count"], 0)
        self.assertIn("no_selected_runs", data["errors"])

    def test_output_is_deterministic(self) -> None:
        self.write_state("run-1", "2026-07-14T10:00:00Z")
        self.write_eval([self.eval_row("run-1")])
        output_a = self.base / "a.json"
        output_b = self.base / "b.json"

        result_a = self.run_cli(required_count=1, output=output_a)
        result_b = self.run_cli(required_count=1, output=output_b)

        self.assertEqual(result_a.returncode, 0)
        self.assertEqual(result_b.returncode, 0)
        self.assertEqual(output_a.read_bytes(), output_b.read_bytes())

    def test_nested_output_parent_is_created_atomically(self) -> None:
        self.write_state("run-1", "2026-07-14T10:00:00Z")
        self.write_eval([self.eval_row("run-1")])
        nested = self.base / "nested" / "audit" / "result.json"

        result = self.run_cli(required_count=1, output=nested)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(nested.exists())
        self.assertTrue(json.loads(nested.read_text(encoding="utf-8"))["valid"])

    def test_secret_like_strings_are_redacted_from_output(self) -> None:
        self.write_state("run-1", "2026-07-14T10:00:00Z")
        self.write_eval([self.eval_row("run-1")])

        result = self.run_cli(required_count=1)
        output_text = self.output.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0)
        for forbidden in ("SECRET", "/tmp/", "https://", "TOKEN", "SPEC", "CHECK"):
            self.assertNotIn(forbidden, output_text)


if __name__ == "__main__":
    unittest.main()
