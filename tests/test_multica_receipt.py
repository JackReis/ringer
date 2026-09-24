#!/usr/bin/env python3
"""Tests for hooks/multica_receipt.py — idempotency, flag-off, missing issue."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from hooks import multica_receipt as mr


class MulticaReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "ringer-state"
        self.state.mkdir()
        (self.state / "receipts").mkdir()
        self.runs = self.state / "runs.jsonl"
        self.env_patch = mock.patch.dict(os.environ, {}, clear=False)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        # Isolate from operator env
        os.environ.pop("MULTICA_ISSUE_ID", None)
        os.environ.pop("RINGER_MULTICA_RECEIPT", None)

    def _write_run(self, run_id: str, verdict: str = "PASS", logged_at: str | None = None) -> dict:
        row = {
            "run_id": run_id,
            "verdict": verdict,
            "task_key": "t1",
            "logged_at": logged_at
            or datetime.now(timezone.utc).isoformat(),
            "notes": "retry=false",
        }
        with self.runs.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        return row

    def test_disabled_by_flag(self) -> None:
        os.environ["RINGER_MULTICA_RECEIPT"] = "0"
        os.environ["MULTICA_ISSUE_ID"] = "AEGI-78"
        self._write_run("run-disabled")
        calls: list[tuple] = []

        def poster(issue, body, dry_run=False):
            calls.append((issue, body, dry_run))
            return {"ok": True}

        result = mr.maybe_post_receipt(
            run_id="run-disabled",
            state_dir_path=self.state,
            poster=poster,
        )
        self.assertEqual("disabled", result.status)
        self.assertEqual([], calls)

    def test_missing_issue_id(self) -> None:
        self._write_run("run-no-issue")
        calls: list = []

        def poster(issue, body, dry_run=False):
            calls.append(issue)
            return {"ok": True}

        result = mr.maybe_post_receipt(
            run_id="run-no-issue",
            state_dir_path=self.state,
            poster=poster,
        )
        self.assertEqual("missing_issue", result.status)
        self.assertEqual([], calls)

    def test_posts_once_and_idempotent(self) -> None:
        os.environ["MULTICA_ISSUE_ID"] = "AEGI-78"
        self._write_run("run-idem", verdict="PASS")
        calls: list[str] = []

        def poster(issue, body, dry_run=False):
            calls.append(body)
            self.assertIn("run_id: run-idem", body)
            self.assertIn("verdict: PASS", body)
            self.assertIn("Multica issue: AEGI-78", body)
            self.assertIn("ringside:", body)
            return {"ok": True}

        first = mr.maybe_post_receipt(
            run_id="run-idem",
            state_dir_path=self.state,
            poster=poster,
        )
        self.assertEqual("posted", first.status)
        self.assertEqual(1, len(calls))

        second = mr.maybe_post_receipt(
            run_id="run-idem",
            state_dir_path=self.state,
            poster=poster,
        )
        self.assertEqual("skipped", second.status)
        self.assertEqual(1, len(calls))

        posted = mr.load_posted(self.state)
        self.assertIn("run-idem", posted)

    def test_force_reposts(self) -> None:
        os.environ["MULTICA_ISSUE_ID"] = "AEGI-78"
        self._write_run("run-force")
        calls: list = []

        def poster(issue, body, dry_run=False):
            calls.append(1)
            return {"ok": True}

        mr.maybe_post_receipt(run_id="run-force", state_dir_path=self.state, poster=poster)
        mr.maybe_post_receipt(
            run_id="run-force", state_dir_path=self.state, poster=poster, force=True
        )
        self.assertEqual(2, len(calls))

    def test_post_failure_is_error_not_exception(self) -> None:
        os.environ["MULTICA_ISSUE_ID"] = "AEGI-78"
        self._write_run("run-failpost")

        def poster(issue, body, dry_run=False):
            return {"ok": False, "returncode": 7, "stderr": "boom"}

        result = mr.maybe_post_receipt(
            run_id="run-failpost",
            state_dir_path=self.state,
            poster=poster,
        )
        self.assertEqual("error", result.status)
        self.assertIn("boom", result.detail)
        # Fail-open: ledger must NOT mark as posted
        self.assertNotIn("run-failpost", mr.load_posted(self.state))

    def test_ringside_withheld_when_stale(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        self._write_run("run-stale", logged_at=old)
        ref = mr.ringside_ref(self.state)
        self.assertEqual("withheld-stale", ref)

    def test_ringside_url_when_fresh(self) -> None:
        self._write_run("run-fresh")
        ref = mr.ringside_ref(self.state)
        self.assertTrue(ref.startswith("http"), ref)

    def test_body_includes_required_fields(self) -> None:
        run = {
            "run_id": "abc",
            "verdict": "FAIL",
            "logged_at": "2026-09-24T12:00:00+00:00",
            "artifact_path": "/tmp/art.md",
        }
        body = mr.format_receipt_body(
            issue_id="AEGI-78",
            run=run,
            ringside="withheld-stale",
        )
        for needle in (
            "run_id: abc",
            "verdict: FAIL",
            "artifact: /tmp/art.md",
            "ringside: withheld-stale",
            "Multica issue: AEGI-78",
            "posted_at:",
        ):
            self.assertIn(needle, body)


if __name__ == "__main__":
    unittest.main()
