#!/usr/bin/env python3
"""Read-only claim-proving verifier for Bead notes-4bwsk."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path("/Users/jack.reis/Documents/=notes")
ARCHIVE = Path("/Users/jack.reis/tracking/archive/legacy-commit-log-20260714T001444Z")
ACTIVE = Path("/Users/jack.reis/tracking/commit-log.md")
CANDIDATE_REPO = Path("/Users/jack.reis/ai-dev/ledger-idempotency-parent")
EXPECTED_COMMIT = "ed159a393b8594587bfce53d59b5a47303498294"
EXPECTED = {
    "active": "dec964d98330c56c4d44865d53b6a9c478a5214066525eb2b8e0758102a29db9",
    "raw": "240e3143520994c7299d20cdcce7358982b8d6c23e1910056eaec143c73876df",
    "ledger_py": "0efefe2f9012b030fa569a00afbf8c1b1dd929bd055064ef7a9815d7277fdf4c",
    "test_ledger_py": "5edc5b7739531a7d7158a230edefee4bfd2ae4f580fbfd72021e36c77868ae92",
}


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, timeout: int = 300) -> str:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(command)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def section_metrics(path: Path) -> dict[str, int | bool]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    starts: list[int] = []
    in_fence = False
    for index, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("### "):
            starts.append(index)
    sections = [
        "".join(lines[start : starts[index + 1] if index + 1 < len(starts) else len(lines)])
        for index, start in enumerate(starts)
    ]
    commit_re = re.compile(r"^- \*\*Commit:\*\*\s+(.+?)\s*$", re.MULTILINE)
    identities = [tuple(value.strip() for value in commit_re.findall(section)) for section in sections]
    return {
        "retired_header": "Status: retired historical compatibility projection" in text,
        "sections": len(sections),
        "commit_field_rows": sum(map(len, identities)),
        "unique_section_identity_tuples": len(set(identities)),
        "excess_duplicate_sections": len(identities) - len(set(identities)),
    }


def paperclip_issue(identifier: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:3110/api/issues/{identifier}", timeout=20) as response:
        return json.load(response)


def paperclip_comments(identifier: str) -> list[dict]:
    with urllib.request.urlopen(f"http://127.0.0.1:3110/api/issues/{identifier}/comments", timeout=20) as response:
        return json.load(response)


def main() -> None:
    evidence: dict[str, object] = {}

    actual_hashes = {
        "active": sha256(ACTIVE),
        "raw": sha256(ARCHIVE / "commit-log.raw.md"),
        "candidate": sha256(ARCHIVE / "commit-log.deduplicated.candidate.md"),
        "ledger_py": sha256(ROOT / "claude/scripts/ledger.py"),
        "test_ledger_py": sha256(ROOT / "claude/scripts/test_ledger.py"),
    }
    assert actual_hashes["active"] == EXPECTED["active"]
    assert actual_hashes["candidate"] == EXPECTED["active"]
    assert actual_hashes["raw"] == EXPECTED["raw"]
    assert actual_hashes["ledger_py"] == EXPECTED["ledger_py"]
    assert actual_hashes["test_ledger_py"] == EXPECTED["test_ledger_py"]
    evidence["hashes"] = actual_hashes

    metrics = section_metrics(ACTIVE)
    assert metrics == {
        "retired_header": True,
        "sections": 1347,
        "commit_field_rows": 1352,
        "unique_section_identity_tuples": 1347,
        "excess_duplicate_sections": 0,
    }
    evidence["active_projection"] = metrics

    jobs_data = json.loads(Path("/Users/jack.reis/.hermes/cron/jobs.json").read_text(encoding="utf-8"))
    jobs = jobs_data if isinstance(jobs_data, list) else jobs_data.get("jobs", [])
    legacy = [job for job in jobs if job.get("id") == "62f9a439503b" or job.get("name") == "hermes-ledger"]
    canonical = [job for job in jobs if job.get("id") == "6c168fc9f871" or job.get("name") == "ai-usage-ledger-sync"]
    assert legacy == []
    assert len(canonical) == 1
    assert canonical[0].get("enabled") is True
    assert canonical[0].get("state") == "scheduled"
    assert canonical[0].get("last_status") == "ok"
    evidence["schedules"] = {
        "legacy_writer_matches": 0,
        "canonical_sync": {
            "id": canonical[0]["id"],
            "enabled": canonical[0]["enabled"],
            "state": canonical[0]["state"],
            "last_status": canonical[0]["last_status"],
        },
    }

    health = run(["/Users/jack.reis/.hermes/scripts/ai-usage-ledger-health.sh"])
    assert "overall_status=ok" in health
    assert "ledger_status=ok" in health
    assert "ledger_rows=3045" in health
    assert "ledger_missing_sources=none" in health
    evidence["canonical_health"] = [
        line for line in health.splitlines()
        if line.startswith(("overall_status=", "ledger_status=", "ledger_rows=", "ledger_missing_sources="))
    ]

    legacy_audit_raw = run([
        "python3",
        "/Users/jack.reis/.hermes/skills/productivity/machine-ai-usage-ledger/scripts/verify_legacy_tracking_ledgers.py",
        "--ledger-script", str(ROOT / "claude/scripts/ledger.py"),
        "--tracking-root", "/Users/jack.reis/tracking",
        "--recent-count", "20",
    ])
    legacy_audit = json.loads(legacy_audit_raw)
    quality = legacy_audit["commit_quality"]
    assert quality["full_excess_duplicate_rows"] == 0
    assert quality["full_sha_rows"] == 1347
    assert quality["full_unique_shas"] == 1347
    evidence["legacy_audit"] = quality

    tests = run([
        "/opt/homebrew/bin/uv", "run", "--with", "pytest", "python", "-m", "pytest",
        "claude/scripts/test_ledger.py", "-q",
    ], cwd=ROOT)
    assert "76 passed" in tests
    evidence["tests"] = "76 passed"

    candidate_head = run(["git", "rev-parse", "HEAD"], cwd=CANDIDATE_REPO).strip()
    remote_branch = run([
        "git", "ls-remote", "git@gitlab.com:jackrei/neural-garden-v2.git",
        "refs/heads/fix/ledger-idempotency-parent",
    ]).split()[0]
    assert candidate_head == EXPECTED_COMMIT
    assert remote_branch == EXPECTED_COMMIT
    evidence["candidate_commit"] = EXPECTED_COMMIT

    with tempfile.TemporaryDirectory(prefix="ringer-ledger-") as temp_dir:
        tracking = Path(temp_dir) / "tracking"
        tracking.mkdir()
        shutil.copy2(ACTIVE, tracking / "commit-log.md")
        environment = {**os.environ, "LEDGER_TRACKING_ROOT": str(tracking)}
        command = [
            "python3", str(ROOT / "claude/scripts/ledger.py"), "append-commit",
            "--repo", str(CANDIDATE_REPO), "--count", "20",
        ]
        first = run(command, env=environment)
        second = run(command, env=environment)
        assert "new=7 skipped=13 total=20" in first
        assert "new=0 skipped=20 total=20" in second
        smoke_metrics = section_metrics(tracking / "commit-log.md")
        assert smoke_metrics["excess_duplicate_sections"] == 0
        evidence["idempotency_smoke"] = {
            "first": first.strip(),
            "second": second.strip(),
            "excess_duplicate_sections": 0,
        }

    roots = [
        Path("/Users/jack.reis/.hermes/scripts"),
        ROOT / "claude/scripts",
        ROOT / "claude/scheduled-tasks",
        Path("/Users/jack.reis/Library/LaunchAgents"),
    ]
    needles = ("ledger.py append-commit", "tracking/commit-log.md", "append-commit --")
    executable_matches: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".sh", ".plist", ".json", ".yaml", ".yml", ".toml"}:
                continue
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            if any(needle in text for needle in needles):
                executable_matches.append(str(path))
    assert executable_matches == []
    evidence["executable_consumer_matches"] = 0

    canonical_ledger_dirs = sorted(
        str(path) for path in Path("/Users/jack.reis/.hermes").glob("ledger*") if path.is_dir()
    )
    usage_writer_jobs = [
        job for job in jobs
        if any(
            needle in json.dumps(job, sort_keys=True)
            for needle in ("ai_usage_ledger", "sync_machine_ledger.py", "/.hermes/ledger")
        )
    ]
    assert canonical_ledger_dirs == ["/Users/jack.reis/.hermes/ledger"]
    assert [job.get("id") for job in usage_writer_jobs] == ["6c168fc9f871"]
    evidence["no_second_usage_ledger"] = {
        "canonical_directories": canonical_ledger_dirs,
        "writer_job_ids": [job["id"] for job in usage_writer_jobs],
        "legacy_projection_contract": "retired historical compatibility projection",
    }

    parent = paperclip_issue("JAC-3383")
    typist = paperclip_issue("JAC-3384")
    judge = paperclip_issue("JAC-3385")
    comment_blob = "\n".join(
        comment.get("body", "")
        for identifier in ("JAC-3383", "JAC-3384")
        for comment in paperclip_comments(identifier)
    )
    assert parent["goalId"] == "8a713de8-a7df-4934-a475-5e7cf2104610"
    assert typist["status"] == "in_review"
    assert judge["status"] == "blocked"
    for needle in (EXPECTED_COMMIT, EXPECTED["raw"], "cd0389e9-1fba-4919-805f-a296730ad249", "notes-4bwsk"):
        assert needle in (comment_blob + "\n" + parent.get("description", "") + "\n" + typist.get("description", ""))
    evidence["paperclip"] = {
        "parent": parent["identifier"],
        "typist_status": typist["status"],
        "judge_status": judge["status"],
        "goal_id": parent["goalId"],
    }

    bead_output = run(["bd", "show", "notes-4bwsk", "--json"], env={**os.environ, "BEADS_DIR": str(ROOT / ".beads")}, cwd=ROOT)
    bead = json.loads(bead_output)[0]
    assert bead["status"] == "in_progress"
    assert bead["external_ref"] == "paperclip://JAC-3383"
    for needle in (EXPECTED_COMMIT, EXPECTED["raw"], "cd0389e9-1fba-4919-805f-a296730ad249"):
        assert needle in bead["notes"]
    evidence["bead"] = {"id": bead["id"], "status": bead["status"], "external_ref": bead["external_ref"]}

    print(json.dumps({"verdict": "PASS", "evidence": evidence}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
