#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_COMPANY_ID = "87c32b8e-f131-4df8-ad8e-963d01b458e7"
ACTIVE_STATUSES = ("in_progress", "todo", "in_review", "blocked")
TRACKED_ISSUES = (
    "JAC-3788",
    "JAC-3787",
    "JAC-3783",
    "JAC-3785",
    "JAC-3747",
    "JAC-3751",
)


def fetch_json(url: str) -> object:
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.load(response)


def classify_lane(issue: dict[str, object]) -> str:
    title = str(issue.get("title", "")).lower()
    status = str(issue.get("status", ""))
    if status == "blocked":
        return "approval-or-dependency"
    if "verify" in title or status == "in_review":
        return "deterministic-verification"
    if "plan" in title or "review" in title:
        return "cheap-reasoning"
    return "bounded-implementation"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paperclip-url", default="http://127.0.0.1:3101")
    parser.add_argument("--company-id", default=DEFAULT_COMPANY_ID)
    parser.add_argument("--output", default="active-work-snapshot.json")
    args = parser.parse_args()

    query = urllib.parse.urlencode({"status": ",".join(ACTIVE_STATUSES), "limit": 200})
    issues_url = f"{args.paperclip_url}/api/companies/{args.company_id}/issues?{query}"
    issues = fetch_json(issues_url)
    if not isinstance(issues, list):
        raise TypeError("Paperclip issues response must be a list")

    active = sorted(issues, key=lambda issue: str(issue.get("updatedAt", "")), reverse=True)
    tracked = []
    for identifier in TRACKED_ISSUES:
        issue = fetch_json(f"{args.paperclip_url}/api/issues/{identifier}")
        if not isinstance(issue, dict):
            raise TypeError(f"Paperclip issue {identifier} response must be an object")
        tracked.append(
            {
                "identifier": identifier,
                "title": issue.get("title"),
                "status": issue.get("status"),
                "priority": issue.get("priority"),
                "lane": classify_lane(issue),
                "updated_at": issue.get("updatedAt"),
            }
        )

    status_counts = {status: 0 for status in ACTIVE_STATUSES}
    for issue in active:
        status = str(issue.get("status", ""))
        if status in status_counts:
            status_counts[status] += 1

    snapshot = {
        "contract": "fleet-active-work-dispatch.v1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "authority": {
            "runner": "aegis",
            "coordination": "paperclip",
            "replica": "talaris-read-only",
            "lifecycle": "beads-unchanged",
        },
        "paperclip_issue": "JAC-3788",
        "active_status_counts": status_counts,
        "active_issue_count": len(active),
        "tracked_priorities": tracked,
        "recent_active": [
            {
                "identifier": issue.get("identifier"),
                "title": issue.get("title"),
                "status": issue.get("status"),
                "priority": issue.get("priority"),
                "lane": classify_lane(issue),
                "updated_at": issue.get("updatedAt"),
            }
            for issue in active[:20]
        ],
        "stop_conditions": [
            "no-beads-writes",
            "no-goal-remaps",
            "no-family-bulletin-data-writes",
            "no-credential-or-service-changes",
            "no-deletes-or-force-pushes",
        ],
    }
    Path(args.output).write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    print(
        f"PASS: captured {len(active)} active issues and {len(tracked)} tracked priorities "
        f"for {snapshot['paperclip_issue']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
