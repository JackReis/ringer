#!/usr/bin/env python3
"""which_host is fail-closed on new run receipts."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import ringer
from ringer import (
    AppConfig,
    EngineConfig,
    StateWriter,
    TaskRuntime,
    TaskSpec,
    WhichHostError,
    format_multica_stamp,
    lint_run_receipt,
    resolve_which_host,
    validate_which_host,
    which_host_is_registered_shell,
    which_host_lane,
)


ROOT = Path(__file__).resolve().parents[1]


def isolated_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("RINGER_WHICH_HOST", None)
    env["RINGER_NO_SELF_UPDATE"] = "1"
    env["RINGER_NO_CATALOG_REFRESH"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra:
        env.update(extra)
    return env


class WhichHostEnumTests(unittest.TestCase):
    def test_accepts_the_locked_enum(self) -> None:
        self.assertEqual("aegis", validate_which_host("aegis"))
        self.assertEqual("talaris", validate_which_host("talaris"))
        self.assertEqual("box", validate_which_host("box"))

    def test_rejects_missing_empty_aliases_and_hostnames(self) -> None:
        rejected = [
            None,
            "",
            " ",
            "  aegis",
            "aegis ",
            "Aegis",
            "AEGIS",
            "Talaris",
            "BOX",
            "scratch",
            "grok",
            "vault",
            "hermes",
            "notes",
            "shell",
            "registered-machine-shell",
            "localhost",
            "talaris.local",
            "aegis.local",
            socket.gethostname(),
        ]
        for value in rejected:
            with self.subTest(value=value):
                with self.assertRaises(WhichHostError) as caught:
                    validate_which_host(value)
                self.assertIn("exactly one of: aegis, talaris, box", str(caught.exception))

    def test_box_is_not_a_registered_shell_host(self) -> None:
        self.assertEqual("scratch", which_host_lane("box"))
        self.assertEqual("registered-machine-shell", which_host_lane("aegis"))
        self.assertEqual("registered-machine-shell", which_host_lane("talaris"))
        self.assertFalse(which_host_is_registered_shell("box"))
        self.assertTrue(which_host_is_registered_shell("aegis"))
        self.assertTrue(which_host_is_registered_shell("talaris"))
        self.assertNotEqual(validate_which_host("box"), "talaris")
        self.assertNotEqual(validate_which_host("box"), "aegis")
        with self.assertRaises(WhichHostError):
            which_host_lane("scratch")

    def test_stamp_cites_runs_id_which_host_and_optional_prover(self) -> None:
        self.assertEqual(
            "runs/job-1 which_host=aegis lane=registered-machine-shell",
            format_multica_stamp("job-1", "aegis"),
        )
        self.assertEqual(
            "runs/job-1 which_host=talaris lane=registered-machine-shell prover=abc123",
            format_multica_stamp("job-1", "talaris", prover_tip="abc123"),
        )
        self.assertEqual(
            "runs/job-1 which_host=box lane=scratch",
            format_multica_stamp("job-1", "box"),
        )
        with self.assertRaises(WhichHostError):
            format_multica_stamp("job-1", "box", prover_tip="not a token")

    def test_resolve_does_not_read_the_hostname_or_fall_through(self) -> None:
        with mock.patch.object(socket, "gethostname", return_value="talaris"):
            with mock.patch.dict(os.environ, isolated_env(), clear=True):
                with self.assertRaises(WhichHostError) as caught:
                    resolve_which_host(None, None)
                self.assertIn("does not infer which_host", str(caught.exception))
                self.assertEqual("box", resolve_which_host("box", "aegis"))
                self.assertEqual("talaris", resolve_which_host(None, "talaris"))
                with self.assertRaises(WhichHostError) as bad_cli:
                    resolve_which_host("hostname", "aegis")
                self.assertIn("--which-host", str(bad_cli.exception))
                self.assertNotIn("fell through", str(bad_cli.exception))

    def test_env_beats_config_and_invalid_env_does_not_fall_through(self) -> None:
        with mock.patch.dict(os.environ, isolated_env({"RINGER_WHICH_HOST": "aegis"}), clear=True):
            self.assertEqual("aegis", resolve_which_host(None, "talaris"))
        with mock.patch.dict(os.environ, isolated_env({"RINGER_WHICH_HOST": ""}), clear=True):
            with self.assertRaises(WhichHostError) as caught:
                resolve_which_host(None, "talaris")
            self.assertIn("RINGER_WHICH_HOST", str(caught.exception))

    def test_config_load_rejects_a_bad_pin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            path = root / "config.toml"
            path.write_text('which_host = "scratch"\n', encoding="utf-8")
            with self.assertRaises(WhichHostError):
                AppConfig.load(path)
            path.write_text('which_host = "box"\n', encoding="utf-8")
            self.assertEqual("box", AppConfig.load(path).which_host)
            path.write_text('state_dir = "/tmp/ringer-which-host"\n', encoding="utf-8")
            self.assertIsNone(AppConfig.load(path).which_host)


class WhichHostReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.state_dir = Path(self._temp.name)

    def writer(self, which_host: str | None) -> StateWriter:
        taskdir = self.state_dir / "task"
        taskdir.mkdir(parents=True, exist_ok=True)
        log_path = taskdir / "worker.log"
        log_path.write_text("ok\n", encoding="utf-8")
        runtime = TaskRuntime(
            task=TaskSpec(
                key="task",
                spec="Do the thing described here in full.",
                check="true",
                engine="mock",
            ),
            taskdir=taskdir,
            log_path=log_path,
            status="pass",
            attempts=1,
            spec_short="do the thing",
        )
        runtime.started_at_monotonic = 1.0
        return StateWriter(
            "run-which-host",
            "Which Host",
            "test-agent",
            self.state_dir,
            {
                "mock": EngineConfig(
                    name="mock",
                    bin=sys.executable,
                    args_template=("-c", "pass"),
                    full_access_args=(),
                    sandbox_args=(),
                )
            },
            datetime(2026, 9, 28, tzinfo=timezone.utc),
            [runtime],
            threading.RLock(),
            which_host=which_host,
        )

    def test_new_snapshot_includes_each_enum_value(self) -> None:
        for host in ("aegis", "talaris", "box"):
            with self.subTest(host=host):
                writer = self.writer(host)
                state = writer.snapshot()
                self.assertEqual(host, state["which_host"])
                writer.flush()
                on_disk = json.loads(writer.path.read_text(encoding="utf-8"))
                self.assertEqual(host, on_disk["which_host"])

    def test_flush_without_which_host_writes_nothing(self) -> None:
        writer = self.writer(None)
        with self.assertRaises(WhichHostError):
            writer.flush()
        self.assertFalse(writer.path.exists())

    def test_invalid_which_host_is_refused_before_a_file_exists(self) -> None:
        with self.assertRaises(WhichHostError):
            self.writer("scratch")
        self.assertFalse((self.state_dir / "runs" / "run-which-host.json").exists())

    def test_historical_missing_field_is_grandfathered_until_strict(self) -> None:
        historical = {"run_id": "old", "identity": "someone"}
        self.assertEqual(
            [
                "WARN: which_host is missing "
                "(grandfathered historical receipt; new writes must include it)"
            ],
            lint_run_receipt(historical, require_which_host=False),
        )
        strict = lint_run_receipt(historical, require_which_host=True)
        self.assertTrue(strict[0].startswith("ERROR:"))
        invalid = lint_run_receipt({"which_host": "boxy"}, require_which_host=False)
        self.assertTrue(invalid[0].startswith("ERROR:"))
        self.assertEqual([], lint_run_receipt({"which_host": "box"}, require_which_host=True))


class WhichHostCliTests(unittest.TestCase):
    def write_tree(self, root: Path, *, which_host_line: str | None) -> tuple[Path, Path]:
        state_dir = root / "state"
        config_path = root / "config.toml"
        manifest_path = root / "manifest.json"
        lines = [
            f"state_dir = {json.dumps(str(state_dir))}",
            "",
        ]
        if which_host_line is not None:
            lines.insert(1, which_host_line)
        lines.extend(
            [
                "[eval]",
                'backend = "jsonl"',
                f"jsonl_path = {json.dumps(str(root / 'runs.jsonl'))}",
                "",
                "[artifact]",
                "enabled = false",
                "",
                "[engines.mock]",
                f"bin = {json.dumps(sys.executable)}",
                "args_template = [",
                f"  {json.dumps(str(ROOT / 'engines' / 'mock_worker.py'))},",
                '  "{spec}",',
                "]",
                "sandbox_args = []",
                "full_access_args = []",
                "",
            ]
        )
        config_path.write_text("\n".join(lines), encoding="utf-8")
        manifest_path.write_text(
            json.dumps(
                {
                    "run_name": "which-host",
                    "workdir": str(root / "work"),
                    "max_parallel": 1,
                    "tasks": [
                        {
                            "key": "task",
                            "engine": "mock",
                            "spec": "MOCK_FILE: out.txt\nready\nMOCK_END\n",
                            "check": "test \"$(cat out.txt)\" = ready",
                            "expect_files": ["out.txt"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return config_path, manifest_path

    def run_cli(self, root: Path, extra: list[str], *, which_host_line: str | None) -> subprocess.CompletedProcess[str]:
        config_path, manifest_path = self.write_tree(root, which_host_line=which_host_line)
        return subprocess.run(
            [
                sys.executable,
                "ringer.py",
                "--config",
                str(config_path),
                "run",
                str(manifest_path),
                "--no-dashboard",
                "--identity",
                "which-host-test",
                *extra,
            ],
            cwd=ROOT,
            env=isolated_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )

    def test_bad_which_host_exits_before_a_receipt_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            proc = self.run_cli(root, ["--which-host", "hostname"], which_host_line='which_host = "aegis"')
            combined = proc.stdout + proc.stderr
            self.assertEqual(2, proc.returncode, combined)
            self.assertIn("exactly one of: aegis, talaris, box", combined)
            self.assertIn("hostname", combined)
            self.assertEqual([], list((root / "state" / "runs").glob("*.json")))

    def test_missing_which_host_exits_before_a_receipt_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            proc = self.run_cli(root, [], which_host_line=None)
            combined = proc.stdout + proc.stderr
            self.assertEqual(2, proc.returncode, combined)
            self.assertIn("which_host is required", combined)
            self.assertEqual([], list((root / "state" / "runs").glob("*.json")))

    def test_run_writes_box_and_check_receipts_rejects_a_bad_historical_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            proc = self.run_cli(root, ["--which-host", "box"], which_host_line='which_host = "aegis"')
            combined = proc.stdout + proc.stderr
            self.assertEqual(0, proc.returncode, combined)
            self.assertIn("which_host: box", combined)
            receipts = list((root / "state" / "runs").glob("*.json"))
            self.assertEqual(1, len(receipts))
            payload = json.loads(receipts[0].read_text(encoding="utf-8"))
            self.assertEqual("box", payload["which_host"])
            self.assertNotEqual("talaris", payload["which_host"])
            self.assertNotEqual("aegis", payload["which_host"])
            stamp = format_multica_stamp(payload["run_id"], payload["which_host"])
            self.assertIn("lane=scratch", stamp)
            self.assertNotIn("registered-machine-shell", stamp)

            grandfather = root / "state" / "runs" / "historical.json"
            grandfather.write_text(json.dumps({"run_id": "historical"}) + "\n", encoding="utf-8")
            warn = subprocess.run(
                [sys.executable, "ringer.py", "--config", str(root / "config.toml"), "check-receipts"],
                cwd=ROOT,
                env=isolated_env(),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
            warn_out = warn.stdout + warn.stderr
            self.assertEqual(0, warn.returncode, warn_out)
            self.assertIn("grandfathered", warn_out)
            self.assertIn("historical.json", warn_out)

            strict = subprocess.run(
                [
                    sys.executable,
                    "ringer.py",
                    "--config",
                    str(root / "config.toml"),
                    "check-receipts",
                    "--strict",
                ],
                cwd=ROOT,
                env=isolated_env(),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
            self.assertEqual(1, strict.returncode, strict.stdout + strict.stderr)
            self.assertIn("historical.json: ERROR:", strict.stdout)

            grandfather.write_text(json.dumps({"run_id": "historical", "which_host": "scratch"}) + "\n", encoding="utf-8")
            invalid = subprocess.run(
                [sys.executable, "ringer.py", "--config", str(root / "config.toml"), "check-receipts"],
                cwd=ROOT,
                env=isolated_env(),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
            self.assertEqual(1, invalid.returncode, invalid.stdout + invalid.stderr)
            self.assertIn("scratch", invalid.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
