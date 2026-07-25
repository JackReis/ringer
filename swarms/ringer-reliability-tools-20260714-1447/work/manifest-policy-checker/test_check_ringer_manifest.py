"""Tests for the stdlib-only Ringer manifest validator."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import check_ringer_manifest as checker


SCRIPT = Path(__file__).with_name("check_ringer_manifest.py")


def long_spec(label: str) -> str:
    """Return a self-contained manifest spec longer than policy minimums."""
    return (
        f"Implement the {label} task entirely from the manifest text. "
        "Create only the expected local artifact, validate the observable behavior, "
        "avoid credentials and provider APIs, and keep all decisions reproducible. "
        "The worker should describe inputs, transformations, verification commands, "
        "and success criteria directly in this task body so no external file is required."
    )


def valid_task(key: str, expected: str) -> dict[str, Any]:
    """Build one valid task fixture."""
    return {
        "key": key,
        "task_type": "implementation",
        "engine": "local-codex",
        "model": "standard-model",
        "provider": "local-provider",
        "spec": long_spec(key),
        "timeout_s": 300,
        "check": "set -euo pipefail\npython -m unittest discover\necho PASS\n",
        "expect_files": [expected],
        "verified": "The task has a deterministic verification sentence.",
    }


def valid_manifest() -> dict[str, Any]:
    """Build a valid three-task manifest fixture."""
    return {
        "schema_version": 3,
        "run_name": "release_2026-07-14",
        "workdir": "/tmp/ringer-release-2026-07-14",
        "max_parallel": 3,
        "worktrees": True,
        "default_engine": "local-codex",
        "tasks": [
            valid_task("task-a", "artifacts/task-a.txt"),
            valid_task("task-b", "artifacts/task-b.txt"),
            valid_task("task-c", "artifacts/task-c.txt"),
        ],
    }


class ManifestCheckerTest(unittest.TestCase):
    """Validate CLI and core behavior."""

    def run_cli(
        self,
        manifest_text: str,
        *extra_args: str,
        output: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run the validator subprocess against a temporary manifest file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            manifest_path = temp_path / "manifest.json"
            manifest_path.write_text(manifest_text, encoding="utf-8")
            args = [sys.executable, str(SCRIPT), str(manifest_path), *extra_args]
            if output is not None:
                args.extend(["--output", str(output)])
            env = os.environ.copy()
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            return subprocess.run(
                args,
                check=False,
                text=True,
                capture_output=True,
                env=env,
            )

    def assert_invalid_code(self, report: dict[str, Any], code: str) -> None:
        """Assert that a report contains an error code."""
        self.assertFalse(report["valid"])
        self.assertIn(code, [finding["code"] for finding in report["errors"]])

    def test_valid_three_task_manifest_core_and_cli(self) -> None:
        """A valid three-task manifest passes core validation and CLI execution."""
        manifest = valid_manifest()
        report = checker.validate_manifest(manifest)
        self.assertTrue(report["valid"])
        self.assertEqual(report["task_count"], 3)
        self.assertEqual(report["findings"], [])

        completed = self.run_cli(json.dumps(manifest))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        cli_report = json.loads(completed.stdout)
        self.assertTrue(cli_report["valid"])
        self.assertEqual(cli_report["task_count"], 3)
        self.assertEqual(completed.stderr, "")

    def test_top_level_contracts(self) -> None:
        """Each top-level contract emits a stable error."""
        cases: list[tuple[str, Any, str]] = [
            ("schema_version", 2, "invalid_schema_version"),
            ("schema_version", True, "invalid_schema_version"),
            ("run_name", "bad slug", "invalid_run_name"),
            ("run_name", "", "invalid_run_name"),
            ("workdir", "", "invalid_workdir"),
            ("max_parallel", 0, "invalid_max_parallel"),
            ("max_parallel", 17, "invalid_max_parallel"),
            ("max_parallel", True, "invalid_max_parallel"),
            ("worktrees", "yes", "invalid_worktrees"),
            ("default_engine", "", "invalid_default_engine"),
            ("tasks", [], "empty_tasks"),
            ("tasks", {}, "invalid_tasks"),
        ]
        for field, value, code in cases:
            with self.subTest(field=field, value=value):
                manifest = valid_manifest()
                manifest[field] = value
                self.assert_invalid_code(checker.validate_manifest(manifest), code)

        for field, code in [
            ("schema_version", "missing_schema_version"),
            ("run_name", "missing_run_name"),
            ("workdir", "missing_workdir"),
            ("max_parallel", "missing_max_parallel"),
            ("worktrees", "missing_worktrees"),
            ("default_engine", "missing_default_engine"),
            ("tasks", "missing_tasks"),
        ]:
            with self.subTest(missing=field):
                manifest = valid_manifest()
                del manifest[field]
                self.assert_invalid_code(checker.validate_manifest(manifest), code)

    def test_duplicate_json_keys_and_task_keys(self) -> None:
        """Duplicate JSON object keys and duplicate task keys are rejected."""
        duplicate_json = (
            '{"schema_version": 3, "schema_version": 3, "run_name": "ok", '
            '"max_parallel": 1, "worktrees": true, "default_engine": "local", '
            '"tasks": []}'
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.json"
            manifest_path.write_text(duplicate_json, encoding="utf-8")
            report = checker.check_manifest_path(manifest_path)
        self.assert_invalid_code(report, "duplicate_json_key")

        manifest = valid_manifest()
        manifest["tasks"][1]["key"] = manifest["tasks"][0]["key"]
        self.assert_invalid_code(checker.validate_manifest(manifest), "duplicate_task_key")

    def test_unsafe_expect_paths(self) -> None:
        """Absolute and traversal-style expected paths are rejected."""
        unsafe_values = [
            "/tmp/out.txt",
            "../out.txt",
            "nested/../out.txt",
            "C:/temp/out.txt",
            "nested\\out.txt",
            "./out.txt",
            "",
        ]
        for unsafe in unsafe_values:
            with self.subTest(path=unsafe):
                manifest = valid_manifest()
                manifest["tasks"][0]["expect_files"] = [unsafe]
                self.assert_invalid_code(
                    checker.validate_manifest(manifest), "unsafe_expect_file_path"
                )

    def test_duplicate_expected_paths(self) -> None:
        """Expected artifact paths must be unique across the manifest."""
        manifest = valid_manifest()
        manifest["tasks"][1]["expect_files"] = ["artifacts/task-a.txt"]
        self.assert_invalid_code(checker.validate_manifest(manifest), "duplicate_expect_file_path")

    def test_prohibited_route_detection_in_route_fields(self) -> None:
        """Engine, model, and provider strings reject the prohibited route."""
        route = "".join(("t", "e", "r", "r", "a"))
        cases = [
            ("default_engine", ["default_engine"], "prohibited_default_engine_route"),
            ("engine", ["tasks", 0, "engine"], "prohibited_task_engine_route"),
            ("model", ["tasks", 0, "model"], "prohibited_task_model_route"),
            ("provider", ["tasks", 0, "provider"], "prohibited_task_provider_route"),
        ]
        for _name, path, code in cases:
            with self.subTest(code=code):
                manifest = valid_manifest()
                target: Any = manifest
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = f"Cloud-{route.upper()}-Lane"
                self.assert_invalid_code(checker.validate_manifest(manifest), code)

    def test_short_and_pointer_only_specs(self) -> None:
        """Specs must be long and self-contained."""
        manifest = valid_manifest()
        manifest["tasks"][0]["spec"] = "Too short."
        self.assert_invalid_code(checker.validate_manifest(manifest), "short_task_spec")

        pointer_manifest = valid_manifest()
        pointer_manifest["tasks"][0]["spec"] = (
            "See ./docs/task.md for the full instructions. "
            "Refer to ./docs/task.md for the implementation spec. "
            "Read ./docs/task.md for all details. "
        ) * 5
        self.assert_invalid_code(
            checker.validate_manifest(pointer_manifest), "pointer_only_task_spec"
        )

    def test_weak_checks(self) -> None:
        """Checks need fail-fast behavior and a PASS marker."""
        manifest = valid_manifest()
        manifest["tasks"][0]["check"] = "python -m unittest discover\necho PASS\n"
        self.assert_invalid_code(checker.validate_manifest(manifest), "check_missing_fail_fast")

        manifest = valid_manifest()
        manifest["tasks"][0]["check"] = "set -euo pipefail\npython -m unittest discover\n"
        self.assert_invalid_code(checker.validate_manifest(manifest), "check_missing_pass_marker")

        manifest = valid_manifest()
        manifest["tasks"][0]["check"] = "python -m unittest discover\n"
        report = checker.validate_manifest(manifest)
        codes = [finding["code"] for finding in report["errors"]]
        self.assertIn("check_missing_fail_fast", codes)
        self.assertIn("check_missing_pass_marker", codes)

    def test_verified_sentence_rules(self) -> None:
        """Verified text must be long enough and end with a period."""
        manifest = valid_manifest()
        manifest["tasks"][0]["verified"] = "Short."
        self.assert_invalid_code(checker.validate_manifest(manifest), "short_verified")

        manifest = valid_manifest()
        manifest["tasks"][0]["verified"] = "This verification sentence is long enough but has no final stop"
        self.assert_invalid_code(
            checker.validate_manifest(manifest), "verified_missing_period"
        )

        manifest = valid_manifest()
        manifest["tasks"][0]["verified"] = 123
        self.assert_invalid_code(checker.validate_manifest(manifest), "invalid_verified")

    def test_strict_warning_behavior(self) -> None:
        """Strict mode makes warnings produce invalid status."""
        manifest = valid_manifest()
        manifest["unused_field"] = "ignored"

        normal = checker.validate_manifest(manifest)
        self.assertTrue(normal["valid"])
        self.assertEqual(len(normal["warnings"]), 1)

        strict = checker.validate_manifest(manifest, strict=True)
        self.assertFalse(strict["valid"])
        self.assertEqual(len(strict["errors"]), 0)
        self.assertEqual(len(strict["warnings"]), 1)

        completed = self.run_cli(json.dumps(manifest), "--strict")
        self.assertEqual(completed.returncode, 1)
        self.assertFalse(json.loads(completed.stdout)["valid"])

    def test_deterministic_finding_order(self) -> None:
        """Repeated validation produces byte-for-byte identical JSON reports."""
        manifest = valid_manifest()
        del manifest["schema_version"]
        manifest["run_name"] = "bad slug"
        manifest["tasks"][0]["check"] = "python -m unittest discover\n"
        first = checker.render_report(checker.validate_manifest(copy.deepcopy(manifest)))
        second = checker.render_report(checker.validate_manifest(copy.deepcopy(manifest)))
        self.assertEqual(first, second)
        codes = [finding["code"] for finding in json.loads(first)["findings"]]
        self.assertEqual(
            codes[:4],
            [
                "missing_schema_version",
                "invalid_run_name",
                "check_missing_fail_fast",
                "check_missing_pass_marker",
            ],
        )

    def test_atomic_output_success_and_failure_cleanup(self) -> None:
        """Output writes replace atomically and clean temporary files on failure."""
        report = checker.validate_manifest(valid_manifest())
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            output_path = temp_path / "report.json"
            output_path.write_text("old", encoding="utf-8")

            completed = self.run_cli(json.dumps(valid_manifest()), output=output_path)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(json.loads(output_path.read_text(encoding="utf-8"))["valid"])
            self.assertEqual(completed.stdout, "")
            self.assertEqual(list(temp_path.glob(".*.tmp")), [])

            output_path.write_text("old", encoding="utf-8")
            with mock.patch.object(checker.os, "replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    checker.write_json_report(report, output_path)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "old")
            self.assertEqual(list(temp_path.glob(".*.tmp")), [])

    def test_malformed_input_and_wrong_top_level(self) -> None:
        """Malformed JSON and wrong top-level types fail cleanly."""
        completed = self.run_cli('{"schema_version": ')
        self.assertEqual(completed.returncode, 1)
        report = json.loads(completed.stdout)
        self.assertFalse(report["valid"])
        self.assertEqual(report["errors"][0]["code"], "malformed_json")
        self.assertNotIn("Traceback", completed.stderr + completed.stdout)

        completed = self.run_cli("[]")
        self.assertEqual(completed.returncode, 1)
        report = json.loads(completed.stdout)
        self.assertEqual(report["errors"][0]["code"], "manifest_not_object")

    def test_output_redaction(self) -> None:
        """Reports do not include full specs, checks, or environment-like values."""
        secret = "SECRET_TOKEN_VALUE_123"
        manifest = valid_manifest()
        manifest["environment"] = {"TOKEN": secret}
        manifest["tasks"][0]["spec"] = f"Read ./secret.md for {secret}. " * 20
        manifest["tasks"][0]["check"] = f"echo {secret}\n"

        completed = self.run_cli(json.dumps(manifest))
        self.assertEqual(completed.returncode, 1)
        combined = completed.stdout + completed.stderr
        self.assertNotIn(secret, combined)
        self.assertNotIn("Read ./secret.md", combined)
        self.assertNotIn("echo", combined)
        self.assertNotIn("Traceback", combined)


if __name__ == "__main__":
    unittest.main()
