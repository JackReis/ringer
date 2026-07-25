"""CLI tests for aggregate_token_usage using temporary SQLite fixtures."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCRIPT = Path(__file__).with_name("aggregate_token_usage.py")
NOW = "2026-07-14T12:00:00Z"


def epoch(iso_utc: str) -> int:
    """Convert an ISO UTC timestamp to Unix epoch seconds."""
    normalized = iso_utc.replace("Z", "+00:00")
    return int(datetime.fromisoformat(normalized).astimezone(timezone.utc).timestamp())


class AggregateTokenUsageCliTest(unittest.TestCase):
    """End-to-end CLI coverage with isolated SQLite databases."""

    maxDiff = None

    def setUp(self) -> None:
        """Create an isolated temporary directory for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def create_db(
        self,
        rows: Iterable[tuple[Any, Any, Any, Any, Any, Any, Any]] = (),
        *,
        schema: str | None = None,
    ) -> Path:
        """Create a temporary SQLite database with optional session rows."""
        db_path = self.root / "usage.sqlite"
        create_sql = schema or """
            CREATE TABLE sessions (
                id TEXT,
                model TEXT,
                started_at INTEGER,
                input_tokens INTEGER,
                output_tokens INTEGER,
                billing_provider TEXT,
                estimated_cost_usd REAL
            )
        """
        with sqlite3.connect(db_path) as conn:
            conn.execute(create_sql)
            row_list = list(rows)
            if row_list:
                conn.executemany(
                    """
                    INSERT INTO sessions (
                        id, model, started_at, input_tokens, output_tokens,
                        billing_provider, estimated_cost_usd
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    row_list,
                )
        return db_path

    def run_cli(
        self,
        db_path: Path,
        *,
        out_24h: Path | None = None,
        out_month: Path | None = None,
        now: str = NOW,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Invoke the CLI in a subprocess."""
        out_24h = out_24h or (self.root / "out-24h.json")
        out_month = out_month or (self.root / "out-month.json")
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "--db",
                str(db_path),
                "--out-24h",
                str(out_24h),
                "--out-month",
                str(out_month),
                "--now",
                now,
            ],
            cwd=SCRIPT.parent,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if check and completed.returncode != 0:
            self.fail(f"CLI failed with {completed.returncode}: {completed.stderr}")
        return completed

    @staticmethod
    def read_json(path: Path) -> dict[str, Any]:
        """Read a JSON object from disk."""
        with path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        assert isinstance(loaded, dict)
        return loaded

    def test_rolling_24h_boundary_and_exclusion(self) -> None:
        """Rows at the exact 24h boundary are included; rows just before it are not."""
        db_path = self.create_db(
            [
                ("boundary", "model-a", epoch("2026-07-13T12:00:00Z"), 1, 2, "provider-a", 0.1),
                ("inside", "model-a", epoch("2026-07-14T12:00:00Z"), 3, 4, "provider-a", 0.2),
                ("outside", "model-b", epoch("2026-07-13T11:59:59Z"), 50, 60, "provider-a", 0.3),
            ]
        )
        out_24h = self.root / "rolling.json"
        self.run_cli(db_path, out_24h=out_24h)

        self.assertEqual(
            self.read_json(out_24h),
            {
                "window": {"start": "2026-07-13T12:00:00Z", "end": NOW},
                "providers": {
                    "provider-a": {
                        "total_input_tokens": 4,
                        "total_output_tokens": 6,
                        "total_estimated_cost_usd": 0.3,
                        "session_count": 2,
                        "models": {
                            "model-a": {"input": 4, "output": 6, "cost": 0.3},
                        },
                    },
                },
                "generated_at": NOW,
            },
        )

    def test_current_month_boundary(self) -> None:
        """The UTC calendar month starts inclusively at midnight on day one."""
        db_path = self.create_db(
            [
                ("month-start", "model-a", epoch("2026-07-01T00:00:00Z"), 10, 20, "provider-a", 0.1111111),
                ("prior-month", "model-a", epoch("2026-06-30T23:59:59Z"), 99, 99, "provider-a", 9.0),
                ("now", "model-b", epoch(NOW), 1, 2, "provider-a", 0.2222222),
            ]
        )
        out_month = self.root / "month.json"
        self.run_cli(db_path, out_month=out_month)

        self.assertEqual(
            self.read_json(out_month),
            {
                "window": {"start": "2026-07-01T00:00:00Z", "end": NOW},
                "providers": {
                    "provider-a": {
                        "total_input_tokens": 11,
                        "total_output_tokens": 22,
                        "total_estimated_cost_usd": 0.333333,
                        "session_count": 2,
                        "models": {
                            "model-a": {"input": 10, "output": 20, "cost": 0.111111},
                            "model-b": {"input": 1, "output": 2, "cost": 0.222222},
                        },
                    },
                },
                "generated_at": NOW,
            },
        )

    def test_multiple_providers_models_and_deterministic_ordering(self) -> None:
        """Providers and models are aggregated and serialized lexicographically."""
        db_path = self.create_db(
            [
                ("z", "z-model", epoch(NOW), 7, 8, "zeta", 0.7),
                ("a2", "z-model", epoch(NOW), 3, 4, "alpha", 0.3),
                ("a1", "a-model", epoch(NOW), 1, 2, "alpha", 0.1),
            ]
        )
        out_24h = self.root / "order.json"
        self.run_cli(db_path, out_24h=out_24h)
        output = self.read_json(out_24h)

        self.assertEqual(list(output["providers"].keys()), ["alpha", "zeta"])
        self.assertEqual(list(output["providers"]["alpha"]["models"].keys()), ["a-model", "z-model"])
        self.assertEqual(
            output,
            {
                "window": {"start": "2026-07-13T12:00:00Z", "end": NOW},
                "providers": {
                    "alpha": {
                        "total_input_tokens": 4,
                        "total_output_tokens": 6,
                        "total_estimated_cost_usd": 0.4,
                        "session_count": 2,
                        "models": {
                            "a-model": {"input": 1, "output": 2, "cost": 0.1},
                            "z-model": {"input": 3, "output": 4, "cost": 0.3},
                        },
                    },
                    "zeta": {
                        "total_input_tokens": 7,
                        "total_output_tokens": 8,
                        "total_estimated_cost_usd": 0.7,
                        "session_count": 1,
                        "models": {
                            "z-model": {"input": 7, "output": 8, "cost": 0.7},
                        },
                    },
                },
                "generated_at": NOW,
            },
        )

    def test_null_normalization_and_zero_row_skipping(self) -> None:
        """Blank/null provider and model values become unknown, and all-zero rows are skipped."""
        db_path = self.create_db(
            [
                ("nulls", None, epoch(NOW), 1, None, None, None),
                ("blanks", "   ", epoch(NOW), None, 2, "   ", ""),
                ("skip-null-zero", "model-a", epoch(NOW), None, 0, "provider-a", None),
                ("skip-zero", "model-b", epoch(NOW), 0, 0, "provider-b", 0.0),
            ]
        )
        out_24h = self.root / "normalized.json"
        self.run_cli(db_path, out_24h=out_24h)

        self.assertEqual(
            self.read_json(out_24h),
            {
                "window": {"start": "2026-07-13T12:00:00Z", "end": NOW},
                "providers": {
                    "unknown": {
                        "total_input_tokens": 1,
                        "total_output_tokens": 2,
                        "total_estimated_cost_usd": 0.0,
                        "session_count": 2,
                        "models": {
                            "unknown": {"input": 1, "output": 2, "cost": 0.0},
                        },
                    },
                },
                "generated_at": NOW,
            },
        )

    def test_cost_rounding(self) -> None:
        """Costs are summed and rounded to six decimal places."""
        db_path = self.create_db(
            [
                ("round-down", "model-a", epoch(NOW), 0, 0, "provider-a", 0.1234564),
                ("round-up", "model-b", epoch(NOW), 0, 0, "provider-a", 0.0000005),
            ]
        )
        out_24h = self.root / "rounding.json"
        self.run_cli(db_path, out_24h=out_24h)

        self.assertEqual(
            self.read_json(out_24h),
            {
                "window": {"start": "2026-07-13T12:00:00Z", "end": NOW},
                "providers": {
                    "provider-a": {
                        "total_input_tokens": 0,
                        "total_output_tokens": 0,
                        "total_estimated_cost_usd": 0.123457,
                        "session_count": 2,
                        "models": {
                            "model-a": {"input": 0, "output": 0, "cost": 0.123456},
                            "model-b": {"input": 0, "output": 0, "cost": 0.000001},
                        },
                    },
                },
                "generated_at": NOW,
            },
        )

    def test_read_only_source_db_behavior(self) -> None:
        """A read-only database file can still be aggregated."""
        db_path = self.create_db(
            [("row", "model-a", epoch(NOW), 5, 6, "provider-a", 0.5)]
        )
        os.chmod(db_path, 0o444)
        out_24h = self.root / "readonly.json"
        self.run_cli(db_path, out_24h=out_24h)

        self.assertEqual(
            self.read_json(out_24h)["providers"]["provider-a"]["total_input_tokens"],
            5,
        )

    def test_atomic_nested_output_creation(self) -> None:
        """Nested output directories are created and temporary files are not left behind."""
        db_path = self.create_db()
        out_24h = self.root / "nested" / "daily" / "usage.json"
        out_month = self.root / "nested" / "monthly" / "usage.json"
        self.run_cli(db_path, out_24h=out_24h, out_month=out_month)

        expected_24h = {
            "window": {"start": "2026-07-13T12:00:00Z", "end": NOW},
            "providers": {},
            "generated_at": NOW,
        }
        expected_month = {
            "window": {"start": "2026-07-01T00:00:00Z", "end": NOW},
            "providers": {},
            "generated_at": NOW,
        }
        self.assertEqual(self.read_json(out_24h), expected_24h)
        self.assertEqual(self.read_json(out_month), expected_month)
        self.assertEqual(
            [path for path in out_24h.parent.iterdir() if path.name.startswith(".usage.json.")],
            [],
        )

    def test_missing_db_fails_cleanly(self) -> None:
        """A missing database path fails nonzero before outputs are written."""
        missing_db = self.root / "missing.sqlite"
        out_24h = self.root / "missing-24h.json"
        out_month = self.root / "missing-month.json"
        completed = self.run_cli(
            missing_db,
            out_24h=out_24h,
            out_month=out_month,
            check=False,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("database not found", completed.stderr)
        self.assertFalse(out_24h.exists())
        self.assertFalse(out_month.exists())

    def test_missing_sessions_table_fails_cleanly(self) -> None:
        """A database without the sessions table fails nonzero."""
        db_path = self.root / "no-sessions.sqlite"
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE other_table (id TEXT)")

        completed = self.run_cli(db_path, check=False)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("missing sessions table", completed.stderr)

    def test_incompatible_schema_fails_cleanly(self) -> None:
        """A sessions table missing required columns fails nonzero."""
        db_path = self.create_db(
            schema="""
                CREATE TABLE sessions (
                    id TEXT,
                    model TEXT,
                    started_at INTEGER,
                    input_tokens INTEGER
                )
            """
        )
        completed = self.run_cli(db_path, check=False)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("incompatible sessions schema", completed.stderr)
        self.assertIn("estimated_cost_usd", completed.stderr)


if __name__ == "__main__":
    unittest.main()
