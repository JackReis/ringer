#!/usr/bin/env python3
"""Weekly scorecard: sot_drift and agent_memory_freshness fail closed."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import ringer
from ringer import (
    resolve_scorecard_max_age_days,
    resolve_scorecard_today,
    scorecard_report,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    "docs/RECEIPTS.md",
    "docs/SCORECARD.md",
    "docs/agent-memory/HARVEST.md",
    "docs/agent-memory/BRANCHES.md",
    "docs/agent-memory/SIMPLIFICATIONS.md",
    "docs/agent-memory/INDEX.json",
    "docs/TAXONOMY.md",
    "docs/STEERING.md",
    ".claude/skills/ringer/SKILL.md",
)


def _axis(report: dict, axis_id: str) -> dict:
    for axis in report["axes"]:
        if axis["id"] == axis_id:
            return axis
    raise AssertionError(axis_id)


def _harvest_date() -> date:
    index = json.loads((ROOT / "docs/agent-memory/INDEX.json").read_text(encoding="utf-8"))
    return datetime.strptime(index["harvested_on"], "%Y-%m-%d").date()


class ScorecardTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        for relative in CONTRACT:
            source = ROOT / relative
            target = self.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def _write_index(self, mutate) -> dict:
        path = self.repo / "docs/agent-memory/INDEX.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        mutate(data)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return data

    def _report(self, *, today: date | None = None, max_age_days: int = 7) -> dict:
        return scorecard_report(
            self.repo,
            today=today or _harvest_date(),
            max_age_days=max_age_days,
        )

    def test_live_tree_passes_on_harvest_date(self) -> None:
        today = _harvest_date()
        report = scorecard_report(ROOT, today=today, max_age_days=7)
        self.assertTrue(report["ok"], report)
        self.assertEqual(
            ["sot_drift", "agent_memory_freshness"],
            [axis["id"] for axis in report["axes"]],
        )
        for axis in report["axes"]:
            self.assertEqual("pass", axis["status"])
            self.assertEqual([], axis["findings"])
        self.assertIn("aegis", ringer.WHICH_HOSTS)
        self.assertIn("talaris", ringer.WHICH_HOSTS)
        self.assertIn("box", ringer.WHICH_HOSTS)
        self.assertEqual("scratch", ringer.which_host_lane("box"))

    def test_copied_tree_passes_when_fresh(self) -> None:
        report = self._report()
        self.assertTrue(report["ok"], report)

    def test_stale_harvested_on_fails_freshness(self) -> None:
        self._write_index(lambda data: data.__setitem__("harvested_on", "2026-09-01"))
        report = self._report(today=date(2026, 9, 28))
        self.assertFalse(report["ok"])
        fresh = _axis(report, "agent_memory_freshness")
        self.assertEqual("fail", fresh["status"])
        self.assertTrue(any("harvested_on 2026-09-01" in item for item in fresh["findings"]))
        self.assertEqual("pass", _axis(report, "sot_drift")["status"])

    def test_age_seven_passes_and_age_eight_fails(self) -> None:
        today = date(2026, 9, 28)
        self._write_index(lambda data: data.__setitem__("harvested_on", "2026-09-21"))
        week = self._report(today=today)
        self.assertEqual("pass", _axis(week, "agent_memory_freshness")["status"], week)
        self._write_index(lambda data: data.__setitem__("harvested_on", "2026-09-20"))
        older = self._report(today=today)
        self.assertEqual("fail", _axis(older, "agent_memory_freshness")["status"])
        self.assertTrue(any("8 days old" in item for item in _axis(older, "agent_memory_freshness")["findings"]))

    def test_enum_contradiction_fails_sot_drift(self) -> None:
        path = self.repo / "docs/RECEIPTS.md"
        path.write_text(path.read_text(encoding="utf-8").replace("| `box` |", "| `scratch` |", 1), encoding="utf-8")
        report = self._report()
        self.assertFalse(report["ok"])
        drift = _axis(report, "sot_drift")
        self.assertEqual("fail", drift["status"])
        self.assertTrue(any("locked enum" in item and "scratch" in item for item in drift["findings"]))
        self.assertTrue(all(item.startswith("ERROR") for item in drift["findings"]))

    def test_missing_index_fails(self) -> None:
        (self.repo / "docs/agent-memory/INDEX.json").unlink()
        report = self._report()
        self.assertFalse(report["ok"])
        fresh = _axis(report, "agent_memory_freshness")
        drift = _axis(report, "sot_drift")
        self.assertEqual("fail", fresh["status"])
        self.assertEqual("fail", drift["status"])
        self.assertTrue(any("INDEX.json is missing" in item for item in fresh["findings"]))
        self.assertTrue(any("INDEX.json is missing" in item for item in drift["findings"]))

    def test_unparseable_and_missing_harvested_on_fail(self) -> None:
        self._write_index(lambda data: data.__setitem__("harvested_on", "September 28"))
        bad = self._report()
        self.assertTrue(any("YYYY-MM-DD" in item for item in _axis(bad, "agent_memory_freshness")["findings"]))
        self._write_index(lambda data: data.pop("harvested_on"))
        missing = self._report()
        self.assertTrue(any("harvested_on is missing" in item for item in _axis(missing, "agent_memory_freshness")["findings"]))

    def test_listed_doc_missing_fails(self) -> None:
        (self.repo / "docs/agent-memory/BRANCHES.md").unlink()
        report = self._report()
        fresh = _axis(report, "agent_memory_freshness")
        self.assertEqual("fail", fresh["status"])
        self.assertTrue(any("listed doc missing: docs/agent-memory/BRANCHES.md" in item for item in fresh["findings"]))

    def test_sha256_mismatch_fails_and_absence_does_not(self) -> None:
        harvest = self.repo / "docs/agent-memory/HARVEST.md"
        digest = hashlib.sha256(harvest.read_bytes()).hexdigest()
        self._write_index(
            lambda data: next(
                entry for entry in data["docs"] if entry["path"].endswith("HARVEST.md")
            ).__setitem__("sha256", digest)
        )
        matched = self._report()
        self.assertTrue(matched["ok"], matched)
        harvest.write_text(harvest.read_text(encoding="utf-8") + "\nextra\n", encoding="utf-8")
        drifted = self._report()
        self.assertEqual("fail", _axis(drifted, "agent_memory_freshness")["status"])
        self.assertTrue(any("sha256 mismatch" in item for item in _axis(drifted, "agent_memory_freshness")["findings"]))

    def test_bad_max_age_does_not_fall_through(self) -> None:
        with mock.patch.dict(os.environ, {"RINGER_SCORECARD_MAX_AGE_DAYS": "weekly"}):
            days, error = resolve_scorecard_max_age_days(None)
        self.assertIsNone(days)
        self.assertIn("RINGER_SCORECARD_MAX_AGE_DAYS", error or "")
        with mock.patch.dict(os.environ, {"RINGER_SCORECARD_MAX_AGE_DAYS": "weekly"}):
            days, error = resolve_scorecard_max_age_days(4)
        self.assertEqual(4, days)
        self.assertIsNone(error)
        parsed, error = resolve_scorecard_today("2026-02-31")
        self.assertIsNone(parsed)
        self.assertIn("ERROR", error or "")

    def _cli(self, args: list[str], env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["RINGER_NO_SELF_UPDATE"] = "1"
        env["RINGER_NO_CATALOG_REFRESH"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.pop("RINGER_SCORECARD_MAX_AGE_DAYS", None)
        env.pop("RINGER_WHICH_HOST", None)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(ROOT / "ringer.py"), *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_cli_json_passes_on_harvest_date(self) -> None:
        today = _harvest_date().isoformat()
        proc = self._cli(["scorecard", "--json", "--today", today])
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(["id", "status", "findings"], list(payload["axes"][0].keys()))
        self.assertEqual("pass", payload["axes"][0]["status"])
        self.assertNotIn("scorecard:", proc.stdout)

    def test_cli_stale_today_exits_1_with_axis_id(self) -> None:
        proc = self._cli(["scorecard", "--today", "2026-10-06"])
        self.assertEqual(1, proc.returncode, proc.stdout + proc.stderr)
        self.assertIn("agent_memory_freshness FAIL", proc.stdout)
        self.assertIn("scorecard: FAIL", proc.stdout)
        self.assertIn("days old", proc.stdout)

    def test_cli_broken_enum_fixture_exits_1(self) -> None:
        path = self.repo / "docs/RECEIPTS.md"
        path.write_text(path.read_text(encoding="utf-8").replace("| `box` |", "| `scratch` |", 1), encoding="utf-8")
        proc = self._cli(
            ["scorecard", "--repo", str(self.repo), "--today", _harvest_date().isoformat()]
        )
        self.assertEqual(1, proc.returncode, proc.stdout + proc.stderr)
        self.assertIn("sot_drift FAIL", proc.stdout)
        self.assertIn("locked enum", proc.stdout)
