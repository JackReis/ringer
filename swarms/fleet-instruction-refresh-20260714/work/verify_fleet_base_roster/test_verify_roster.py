import json
import tempfile
import unittest
from pathlib import Path

import verify_roster


class VerifyRosterTest(unittest.TestCase):
    def test_writes_expected_report_from_agent_ids_section_and_api(self):
        fleet_base = """# Fleet Base

- Outside: `00000000-0000-0000-0000-000000000000`

### Agent IDs (for delegation)

- Coordinator: `11111111-1111-1111-1111-111111111111`
- Task Rabbit: `22222222-2222-2222-2222-222222222222`

### Next Section

- Also Outside: `33333333-3333-3333-3333-333333333333`
"""
        api_payload = [
            {"id": "11111111-1111-1111-1111-111111111111", "name": "Coordinator"},
            {"id": "44444444-4444-4444-4444-444444444444", "name": "Scout"},
        ]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fleet_path = root / "fleet-base.md"
            api_path = root / "agents.json"
            report_path = root / "report.json"
            fleet_path.write_text(fleet_base)
            api_path.write_text(json.dumps(api_payload))

            verify = getattr(verify_roster, "verify_roster", lambda *args: None)
            report = verify(str(fleet_path), api_path.as_uri(), str(report_path))

            expected = {
                "fleet_base_agents": ["Coordinator", "Task Rabbit"],
                "api_agents": ["Coordinator", "Scout"],
                "in_base_not_api": ["Task Rabbit"],
                "in_api_not_base": ["Scout"],
                "match": False,
            }
            self.assertEqual(expected, report)
            self.assertEqual(expected, json.loads(report_path.read_text()))


if __name__ == "__main__":
    unittest.main()
