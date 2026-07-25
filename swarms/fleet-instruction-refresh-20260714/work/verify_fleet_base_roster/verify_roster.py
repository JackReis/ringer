"""Verify the fleet-base roster against the live Paperclip agent list."""

import json
import re
import urllib.request


FLEET_BASE_PATH = (
    "/Users/hermes/.paperclip/instances/default/companies/"
    "87c32b8e-f131-4df8-ad8e-963d01b458e7/fleet-base.md"
)
API_URL = (
    "http://127.0.0.1:3100/api/companies/"
    "87c32b8e-f131-4df8-ad8e-963d01b458e7/agents"
)
REPORT_PATH = "./roster_verification_report.json"


def verify_roster(fleet_base_path, api_url, report_path):
    with open(fleet_base_path, encoding="utf-8") as fleet_file:
        fleet_base = fleet_file.read()

    section_match = re.search(
        r"(?ms)^#{1,6}\s+Agent IDs(?:\s*\([^\n]*\))?\s*$\n"
        r"(.*?)(?=^#{1,6}\s|\Z)",
        fleet_base,
    )
    agent_ids_section = section_match.group(1) if section_match else ""
    fleet_base_agents = re.findall(
        r"(?m)^-\s+(.+?):\s+`"
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}`",
        agent_ids_section,
    )

    with urllib.request.urlopen(api_url) as response:
        api_payload = json.load(response)
    api_agents = [agent["name"] for agent in api_payload]

    api_names = set(api_agents)
    fleet_base_names = set(fleet_base_agents)
    in_base_not_api = [
        name for name in fleet_base_agents if name not in api_names
    ]
    in_api_not_base = [
        name for name in api_agents if name not in fleet_base_names
    ]

    report = {
        "fleet_base_agents": fleet_base_agents,
        "api_agents": api_agents,
        "in_base_not_api": in_base_not_api,
        "in_api_not_base": in_api_not_base,
        "match": not in_base_not_api and not in_api_not_base,
    }
    with open(report_path, "w", encoding="utf-8") as report_file:
        json.dump(report, report_file, indent=2)
        report_file.write("\n")

    return report


if __name__ == "__main__":
    result = verify_roster(FLEET_BASE_PATH, API_URL, REPORT_PATH)
    print(f"Fleet-base agents: {len(result['fleet_base_agents'])}")
    print(f"API agents: {len(result['api_agents'])}")
    print(
        "In fleet-base.md but not API: "
        + (", ".join(result["in_base_not_api"]) or "none")
    )
    print(
        "In API but not fleet-base.md: "
        + (", ".join(result["in_api_not_base"]) or "none")
    )
    print(f"Match: {str(result['match']).lower()}")
