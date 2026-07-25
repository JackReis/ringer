#!/usr/bin/env python3

import json
from pathlib import Path


AGENTS_ROOT = Path(
    "/Users/hermes/.paperclip/instances/default/companies/"
    "87c32b8e-f131-4df8-ad8e-963d01b458e7/agents"
)
REPORT_PATH = Path(__file__).with_name("refresh_report.json")
GOVERNANCE_BLOCK = ""


def refresh(root, report_path):
    report = {"scanned": 0, "updated": [], "skipped": [], "errors": []}
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return report


def main():
    report = refresh(AGENTS_ROOT, REPORT_PATH)
    print(f"Scanned: {report['scanned']}")
    print(f"Updated: {len(report['updated'])}")
    print(f"Skipped: {len(report['skipped'])}")
    print(f"Errors: {len(report['errors'])}")


if __name__ == "__main__":
    main()
