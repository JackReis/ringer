#!/usr/bin/env python3
"""Aegis-side immutable verifier wrapper for native Ringer."""
from __future__ import annotations

import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

JOB = Path("/Users/hermes/ringer/jobs/degraded-ledger-resolution")
REMOTE_VERIFIER = "/Users/jack.reis/tracking/archive/legacy-commit-log-20260714T001444Z/verify_resolution.py"
EXPECTED_REMOTE_VERIFIER_SHA = "9350660a5f5054d4f185bd889d420ed398fdfd3bd6b1caee54cc02022890179e"
EXPECTED_PACKAGE = {
    "archive-manifest.json": "9a985c5ec4e834ea29a01bda3f3cd729ad24e1ad573253505f4fcfbbd52b6374",
    "talaris-verifier.py": EXPECTED_REMOTE_VERIFIER_SHA,
    "bifrost-receipt.json": "049780972e9610f6d09dba0566d76514183572608caaa0b538a5db3ebffd7f1c",
    "pre-repair-red.md": "9c1733b34e72ac347c71eee30eff07b01fab5751df1606ef6fe507bfc56d3e3a",
}


def run(command: list[str], timeout: int = 600) -> str:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(command)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    package_hashes = {name: sha256(JOB / name) for name in EXPECTED_PACKAGE}
    assert package_hashes == EXPECTED_PACKAGE

    remote_hash_output = run([
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "talaris",
        "shasum", "-a", "256", REMOTE_VERIFIER,
    ])
    remote_hash = remote_hash_output.split()[0]
    assert remote_hash == EXPECTED_REMOTE_VERIFIER_SHA

    remote_output = run([
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "talaris",
        "python3", REMOTE_VERIFIER,
    ])
    remote_receipt = json.loads(remote_output)
    assert remote_receipt["verdict"] == "PASS"

    with urllib.request.urlopen("http://127.0.0.1:8078/api/logs?limit=100", timeout=20) as response:
        logs_payload = json.load(response)
    logs = logs_payload.get("logs", logs_payload.get("data", logs_payload if isinstance(logs_payload, list) else []))
    success = next(row for row in logs if row.get("id") == "cd0389e9-1fba-4919-805f-a296730ad249")
    error = next(row for row in logs if row.get("id") == "e650aebf-ec0b-43b7-8ae5-7b6fad7d2dc3")
    assert success["status"] == "success"
    assert success["provider"] == "mistral"
    assert success["model"] == "mistral-small-latest"
    assert error["status"] == "error"
    assert error["error_details"]["status_code"] == 429
    assert any(
        "degraded-ledger-resolution-20260714" in json.dumps(item)
        for item in success.get("input_history", [])
    )

    archive_manifest = json.loads((JOB / "archive-manifest.json").read_text(encoding="utf-8"))
    assert archive_manifest["compatibility_code"]["candidate_commit"] == "ed159a393b8594587bfce53d59b5a47303498294"
    assert archive_manifest["live_cutover"]["active_projection_excess_duplicate_sections"] == 0
    assert archive_manifest["retired_writer"]["state"] == "removed"
    assert archive_manifest["bifrost_receipt"]["success_log_id"] == success["id"]

    print(json.dumps({
        "verdict": "PASS",
        "package_hashes": package_hashes,
        "talaris_verifier_sha256": remote_hash,
        "talaris": remote_receipt["evidence"],
        "bifrost": {
            "success_log_id": success["id"],
            "status": success["status"],
            "provider": success["provider"],
            "model": success["model"],
            "error_attempt_log_id": error["id"],
            "error_attempt_status": error["status"],
        },
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
