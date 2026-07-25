#!/usr/bin/env python3
"""Black-box tests for consistency_audit.py using real files and processes."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("consistency_audit.py")


def valid_document(name="Valid Agent"):
    return f"""# {name}

## Ringer Governance

Follow Ringer governance through Herdr.

## Fleet Context

See [fleet-surfaces-index.md](../../../fleet-surfaces-index.md).
See [fleet-base.md](../../../fleet-base.md).

### Runtime Context

Run on the assigned host.

### Memory Planes

Use the assigned memory planes.
"""


class AuditCliTests(unittest.TestCase):
    def run_audit(self, documents):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            agents_dir = root / "agents"
            report_path = root / "report.json"
            for agent_id, content in documents.items():
                instructions_dir = agents_dir / agent_id / "instructions"
                instructions_dir.mkdir(parents=True)
                (instructions_dir / "AGENTS.md").write_text(
                    content, encoding="utf-8"
                )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--agents-dir",
                    str(agents_dir),
                    "--report",
                    str(report_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            report = (
                json.loads(report_path.read_text(encoding="utf-8"))
                if report_path.exists()
                else None
            )
            return completed, report

    def test_valid_file_passes_every_check_and_matches_json_contract(self):
        completed, report = self.run_audit({"agent-valid": valid_document()})

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(set(report), {"total_files", "all_pass", "files"})
        self.assertEqual(report["total_files"], 1)
        self.assertTrue(report["all_pass"])
        self.assertEqual(len(report["files"]), 1)
        result = report["files"][0]
        self.assertEqual(
            set(result), {"agent_id", "agent_name", "checks", "issues"}
        )
        self.assertEqual(result["agent_id"], "agent-valid")
        self.assertEqual(result["agent_name"], "Valid Agent")
        self.assertEqual(
            list(result["checks"]),
            [
                "heading_h1",
                "ringer_governance",
                "fleet_context",
                "runtime_context_h3",
                "memory_planes_h3",
                "surfaces_ref",
                "fleet_base_ref",
                "herdr_ref",
                "section_order",
                "no_duplicates",
            ],
        )
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["issues"], [])
        self.assertIn("Valid Agent", completed.stdout)
        self.assertIn("PASS", completed.stdout)

    def test_each_required_check_reports_failure(self):
        base = valid_document()
        cases = {
            "heading_h1": base.replace("# Valid Agent", "Valid Agent", 1),
            "ringer_governance": base.replace("## Ringer Governance", "## Governance", 1),
            "fleet_context": base.replace("## Fleet Context", "## Fleet Overview", 1),
            "runtime_context_h3": base.replace("### Runtime Context", "## Runtime Context", 1),
            "memory_planes_h3": base.replace("### Memory Planes", "## Memory Planes", 1),
            "surfaces_ref": base.replace("fleet-surfaces-index.md", "surfaces.md", 1),
            "fleet_base_ref": base.replace("fleet-base.md", "base.md", 1),
            "herdr_ref": base.replace("Herdr", "the coordinator", 1),
            "section_order": base.replace(
                "## Ringer Governance\n\nFollow Ringer governance through Herdr.\n\n## Fleet Context",
                "## Fleet Context\n\nFollow Ringer governance through Herdr.\n\n## Ringer Governance",
                1,
            ),
            "no_duplicates": base + "\n## Fleet Context\n",
        }

        for check_name, document in cases.items():
            with self.subTest(check_name=check_name):
                completed, report = self.run_audit({"agent-fail": document})
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertFalse(report["all_pass"])
                result = report["files"][0]
                self.assertFalse(result["checks"][check_name])
                self.assertTrue(result["issues"])
                self.assertIn("FAIL", completed.stdout)

    def test_runtime_and_memory_headings_must_be_inside_fleet_context(self):
        document = valid_document().replace(
            "### Runtime Context\n\nRun on the assigned host.\n\n"
            "### Memory Planes\n\nUse the assigned memory planes.\n",
            "",
        )
        document += """
## Unrelated Section

### Runtime Context

Outside Fleet Context.

### Memory Planes

Outside Fleet Context.
"""

        completed, report = self.run_audit({"agent-nesting": document})

        self.assertEqual(completed.returncode, 0, completed.stderr)
        checks = report["files"][0]["checks"]
        self.assertFalse(checks["runtime_context_h3"])
        self.assertFalse(checks["memory_planes_h3"])

    def test_fenced_code_headings_do_not_count_as_sections_or_duplicates(self):
        document = valid_document() + """
```markdown
## Fleet Context
### Runtime Context
### Memory Planes
```
"""
        missing_real_sections = """# Fenced Only

fleet-surfaces-index.md fleet-base.md Herdr

```markdown
## Ringer Governance
## Fleet Context
### Runtime Context
### Memory Planes
```
"""

        completed, report = self.run_audit(
            {
                "agent-real": document,
                "agent-fenced": missing_real_sections,
            }
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        by_id = {item["agent_id"]: item for item in report["files"]}
        self.assertTrue(by_id["agent-real"]["checks"]["no_duplicates"])
        fenced_checks = by_id["agent-fenced"]["checks"]
        self.assertFalse(fenced_checks["ringer_governance"])
        self.assertFalse(fenced_checks["fleet_context"])
        self.assertFalse(fenced_checks["runtime_context_h3"])
        self.assertFalse(fenced_checks["memory_planes_h3"])

    def test_files_are_discovered_and_reported_in_agent_id_order(self):
        completed, report = self.run_audit(
            {
                "z-agent": valid_document("Zulu"),
                "a-agent": valid_document("Alpha"),
            }
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(report["total_files"], 2)
        self.assertEqual(
            [item["agent_id"] for item in report["files"]],
            ["a-agent", "z-agent"],
        )
        self.assertLess(completed.stdout.index("Alpha"), completed.stdout.index("Zulu"))

    def test_empty_agent_tree_is_not_an_all_pass(self):
        completed, report = self.run_audit({})

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(report["total_files"], 0)
        self.assertFalse(report["all_pass"])
        self.assertEqual(report["files"], [])


if __name__ == "__main__":
    unittest.main()
