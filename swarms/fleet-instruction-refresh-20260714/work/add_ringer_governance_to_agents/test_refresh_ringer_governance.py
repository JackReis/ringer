import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import refresh_ringer_governance as refresh_module


EXPECTED_BLOCK = """## Ringer Governance

Complex tasks (multi-step plans, architectural decisions, cross-agent work)
follow the Ringer pattern — a Judge/Typist separation:
- **Judge** (high-reasoning model): plans, reviews, approves
- **Typist** (fast executor): implements, tests, reports
- Mandatory check-gates prevent hallucinations from becoming system failures
- **Ringer clone**: `/Users/hermes/ringer/` — README.md has manifest schema
- **Ringside**: http://127.0.0.1:8700 — live swarm dashboard, auto-opens on run
- **Config**: `~/.config/ringer/config.toml` — engines: codex, opencode
- **Post-run hooks** (`~/.ringer/hooks/`):
  - `paperclip_projector.py` — auto-projects verdicts to Paperclip issue comments and Beads comments
  - `preflight_talaris.py` — collects Talaris-side evidence via SSH before sandbox
- **Manifest integration**: task specs may include `paperclip_issue` and `bead_id` fields to wire Ringer verdicts back into fleet tracking systems"""


class RefreshRingerGovernanceTests(unittest.TestCase):
    def make_agent(self, root, agent_id, content):
        path = root / agent_id / "instructions" / "AGENTS.md"
        path.parent.mkdir(parents=True)
        path.write_bytes(content)
        return path

    def test_exact_governance_block_is_used(self):
        self.assertEqual(refresh_module.GOVERNANCE_BLOCK, EXPECTED_BLOCK)

    def test_refresh_inserts_before_fleet_context_and_reports_h1_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "agents"
            report_path = Path(directory) / "report.json"
            original = b"# Alpha\n\nIntro.\n\n## Fleet Context\n\nKeep this.\n"
            path = self.make_agent(root, "alpha-uuid", original)

            report = refresh_module.refresh(root, report_path)

            expected = original.replace(
                b"## Fleet Context",
                EXPECTED_BLOCK.encode("utf-8") + b"\n\n## Fleet Context",
                1,
            )
            self.assertEqual(path.read_bytes(), expected)
            self.assertEqual(
                report,
                {"scanned": 1, "updated": ["Alpha"], "skipped": [], "errors": []},
            )
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8")), report)

    def test_refresh_appends_at_end_when_fleet_context_is_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "agents"
            report_path = Path(directory) / "report.json"
            original = b"# Beta\n\nStay sharp."
            path = self.make_agent(root, "beta-uuid", original)

            refresh_module.refresh(root, report_path)

            self.assertEqual(
                path.read_bytes(),
                original + b"\n\n" + EXPECTED_BLOCK.encode("utf-8") + b"\n",
            )

    def test_refresh_skips_existing_governance_without_rewriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "agents"
            report_path = Path(directory) / "report.json"
            original = ("# Gamma\n\n" + EXPECTED_BLOCK + "\n").encode("utf-8")
            path = self.make_agent(root, "gamma-uuid", original)
            before = path.stat().st_mtime_ns

            report = refresh_module.refresh(root, report_path)

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(path.stat().st_mtime_ns, before)
            self.assertEqual(report["updated"], [])
            self.assertEqual(report["skipped"], ["Gamma"])

    def test_refresh_scans_only_agent_instruction_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "agents"
            report_path = Path(directory) / "report.json"
            self.make_agent(root, "real-uuid", b"# Real\n")
            cached = root / "real-uuid" / "codex-home" / "plugins" / "AGENTS.md"
            cached.parent.mkdir(parents=True)
            cached.write_bytes(b"# Cached Plugin\n")

            report = refresh_module.refresh(root, report_path)

            self.assertEqual(report["scanned"], 1)
            self.assertEqual(report["updated"], ["Real"])
            self.assertEqual(cached.read_bytes(), b"# Cached Plugin\n")

    def test_refresh_records_per_file_write_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "agents"
            report_path = Path(directory) / "report.json"
            path = self.make_agent(root, "delta-uuid", b"# Delta\n")
            path.chmod(0o400)
            try:
                report = refresh_module.refresh(root, report_path)
            finally:
                path.chmod(0o600)

            self.assertEqual(report["scanned"], 1)
            self.assertEqual(report["updated"], [])
            self.assertEqual(report["skipped"], [])
            self.assertEqual(len(report["errors"]), 1)
            self.assertIn("Delta", report["errors"][0])
            self.assertEqual(path.read_bytes(), b"# Delta\n")

    def test_main_prints_summary_and_writes_configured_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "agents"
            report_path = Path(directory) / "report.json"
            self.make_agent(
                root,
                "echo-uuid",
                ("# Echo\n\n" + EXPECTED_BLOCK + "\n").encode("utf-8"),
            )
            old_root = refresh_module.AGENTS_ROOT
            old_report = refresh_module.REPORT_PATH
            refresh_module.AGENTS_ROOT = root
            refresh_module.REPORT_PATH = report_path
            output = io.StringIO()
            try:
                with contextlib.redirect_stdout(output):
                    refresh_module.main()
            finally:
                refresh_module.AGENTS_ROOT = old_root
                refresh_module.REPORT_PATH = old_report

            self.assertEqual(
                output.getvalue(),
                "Scanned: 1\nUpdated: 0\nSkipped: 1\nErrors: 0\n",
            )
            self.assertTrue(report_path.is_file())


if __name__ == "__main__":
    unittest.main()
