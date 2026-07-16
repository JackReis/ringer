#!/usr/bin/env python3
"""Executed oracle for the Fleet Wave controller candidate-custody wave."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

SOURCE_CONTROLLER_SHA = "c5bd1cdd1c8b1fdf56d181ab74fff876aa9f5734"
CANDIDATE_BRANCH = "candidate/fleet-wave-controller-20260716-v5"
EXPECTED_BASE_BRANCH = "fleet-sync/paperclip-to-ringer-20260709"
EXPECTED_BASE_SHA = "8c837910840fd6f4dac8c3792a48fd4624a14d8c"
EXPECTED_STATUS_SHA256 = "8750b0ff530ac509e1da96263073cb0b15f160a17754b0b1e95629ce13a02c08"
SOURCE_FILES = {
    "docs/fleet-wave-protocol.md": "fdadad89e362b3dea8eed70c6472c238751c80a4a38802eb5293d1b2697367f2",
    "schema/fleet-wave-receipt.v1.json": "ed3a20ffd62c7ef85463483e8b0aa2431b94dceaf5c98ef4e7dbc7bf8b8d48bf",
    "schema/fleet-wave.v1.json": "2fd992d4eb9e8239a098390b96619884d4b52f2a7e1acc99a00c09a8a74be8f7",
    "templates/fleet-wave/manifest-v1.json": "307096adc11f991970b817c71ee1d00bb0c98df73896c5a728635ddb61d06254",
    "tests/test_fleet_wave.py": "0f72b3c68cd3c0a0b9b101104208510b23484f603bb7190c46565137412761e0",
    "tools/fleet_wave.py": "0b26439ace7dde172a739892c33225a961f5cafa9acf18d3af673ee01b28b7e7",
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class CheckFailure(RuntimeError):
    pass


def run(command: list[str], *, cwd: Path | None = None, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode:
        rendered = " ".join(command)
        raise CheckFailure(
            f"command failed ({result.returncode}): {rendered}\n"
            f"stdout:\n{result.stdout[-6000:]}\nstderr:\n{result.stderr[-6000:]}"
        )
    return result


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_nonempty(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise CheckFailure(f"required non-empty file missing: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", default="candidate.json")
    parser.add_argument("--bundle", default="candidate.bundle")
    parser.add_argument("--patch", default="integration.patch")
    parser.add_argument("--report", default="integration-report.md")
    parser.add_argument("--changed", default="changed-files.txt")
    args = parser.parse_args()

    candidate_path = Path(args.candidate)
    bundle_path = Path(args.bundle)
    patch_path = Path(args.patch)
    report_path = Path(args.report)
    changed_path = Path(args.changed)
    for path in (candidate_path, bundle_path, patch_path, report_path, changed_path):
        require_nonempty(path)

    try:
        data = json.loads(candidate_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckFailure(f"candidate.json is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CheckFailure("candidate.json must be an object")

    required = {
        "schema_version",
        "source_controller_sha",
        "base_branch",
        "base_sha",
        "candidate_branch",
        "candidate_sha",
        "canonical_checkout_mutated",
        "merged",
        "deployed",
        "source_files",
        "tests",
        "patch_sha256",
        "canonical_checkout",
    }
    missing = sorted(required - set(data))
    if missing:
        raise CheckFailure(f"candidate.json missing keys: {missing}")
    if data["schema_version"] != "fleet-wave-candidate.v1":
        raise CheckFailure("unexpected candidate schema_version")
    if data["source_controller_sha"] != SOURCE_CONTROLLER_SHA:
        raise CheckFailure("source controller SHA does not match the reviewed source revision")
    if data["candidate_branch"] != CANDIDATE_BRANCH:
        raise CheckFailure("candidate branch name mismatch")
    if data["base_branch"] != EXPECTED_BASE_BRANCH or data["base_sha"] != EXPECTED_BASE_SHA:
        raise CheckFailure("candidate base branch/HEAD does not match the manifest-bound Aegis checkout")
    for field in ("base_sha", "candidate_sha"):
        if not isinstance(data[field], str) or not SHA_RE.fullmatch(data[field]):
            raise CheckFailure(f"{field} is not a full lowercase Git SHA")
    if data["base_sha"] == data["candidate_sha"]:
        raise CheckFailure("candidate SHA equals base SHA")
    for field in ("canonical_checkout_mutated", "merged", "deployed"):
        if data[field] is not False:
            raise CheckFailure(f"{field} must be false for this candidate-only wave")
    checkout = data["canonical_checkout"]
    checkout_keys = {
        "path",
        "branch_before",
        "branch_after",
        "head_before",
        "head_after",
        "status_sha256_before",
        "status_sha256_after",
    }
    if not isinstance(checkout, dict) or set(checkout) != checkout_keys:
        raise CheckFailure("canonical_checkout has an unexpected shape")
    if checkout["path"] != "/Users/hermes/ringer":
        raise CheckFailure("canonical checkout path mismatch")
    if (checkout["branch_before"], checkout["branch_after"]) != (EXPECTED_BASE_BRANCH, EXPECTED_BASE_BRANCH):
        raise CheckFailure("canonical checkout branch does not match the manifest-bound branch")
    if (checkout["head_before"], checkout["head_after"]) != (EXPECTED_BASE_SHA, EXPECTED_BASE_SHA):
        raise CheckFailure("canonical checkout HEAD does not match the manifest-bound SHA")
    for field in ("head_before", "head_after"):
        if not isinstance(checkout[field], str) or not SHA_RE.fullmatch(checkout[field]):
            raise CheckFailure(f"canonical_checkout.{field} is not a full Git SHA")
    for field in ("status_sha256_before", "status_sha256_after"):
        if not isinstance(checkout[field], str) or not re.fullmatch(r"[0-9a-f]{64}", checkout[field]):
            raise CheckFailure(f"canonical_checkout.{field} is not a SHA-256 digest")
    if (checkout["status_sha256_before"], checkout["status_sha256_after"]) != (
        EXPECTED_STATUS_SHA256,
        EXPECTED_STATUS_SHA256,
    ):
        raise CheckFailure("canonical checkout status does not match the manifest-bound digest")
    if data["source_files"] != SOURCE_FILES:
        raise CheckFailure("source file hash map does not match the reviewed controller revision")
    if data["patch_sha256"] != sha256(patch_path):
        raise CheckFailure("integration.patch hash does not match candidate.json")
    tests = data["tests"]
    if not isinstance(tests, list) or not tests:
        raise CheckFailure("candidate.json must record at least one executed test")
    if any(not isinstance(item, dict) or item.get("exit_code") != 0 for item in tests):
        raise CheckFailure("candidate.json records a missing or failed test")

    changed = [line.strip() for line in changed_path.read_text().splitlines() if line.strip()]
    if changed != sorted(SOURCE_FILES):
        raise CheckFailure(f"changed-files.txt is not the exact allowed path set: {changed}")

    report = report_path.read_text()
    for phrase in (
        "candidate only",
        "not merged",
        "not deployed",
        data["base_sha"],
        data["candidate_sha"],
        SOURCE_CONTROLLER_SHA,
    ):
        if phrase.lower() not in report.lower():
            raise CheckFailure(f"integration report missing required evidence: {phrase}")

    # Keep independent replay self-contained: create disposable bare repository
    # context for `git bundle verify` instead of reading the live user checkout.
    with tempfile.TemporaryDirectory(prefix="fleet-wave-bundle-verify-") as verify_temp:
        bare = Path(verify_temp) / "verify.git"
        run(["git", "init", "--bare", str(bare)])
        run(["git", "-C", str(bare), "bundle", "verify", str(bundle_path.resolve())])
    heads = run(["git", "bundle", "list-heads", str(bundle_path.resolve())]).stdout.splitlines()
    expected_head = f"{data['candidate_sha']} refs/heads/{CANDIDATE_BRANCH}"
    if expected_head not in heads:
        raise CheckFailure(f"bundle lacks exact candidate branch head: {expected_head}")

    with tempfile.TemporaryDirectory(prefix="fleet-wave-candidate-check-") as temp:
        clone = Path(temp) / "repo"
        run(["git", "clone", "--quiet", str(bundle_path.resolve()), str(clone)], timeout=300)
        actual = run(["git", "rev-parse", "HEAD"], cwd=clone).stdout.strip()
        if actual != data["candidate_sha"]:
            raise CheckFailure(f"bundle checkout HEAD {actual} != recorded candidate SHA")
        run(["git", "cat-file", "-e", f"{data['base_sha']}^{{commit}}"], cwd=clone)
        run(["git", "merge-base", "--is-ancestor", data["base_sha"], data["candidate_sha"]], cwd=clone)
        commit_count = run(
            ["git", "rev-list", "--count", f"{data['base_sha']}..{data['candidate_sha']}"], cwd=clone
        ).stdout.strip()
        if commit_count != "1":
            raise CheckFailure(f"candidate must be exactly one commit over base, found {commit_count}")
        diff_paths = run(
            ["git", "diff", "--name-only", f"{data['base_sha']}..{data['candidate_sha']}"], cwd=clone
        ).stdout.splitlines()
        if diff_paths != sorted(SOURCE_FILES):
            raise CheckFailure(f"candidate changed paths outside exact allowlist: {diff_paths}")
        for relative, expected_sha in SOURCE_FILES.items():
            path = clone / relative
            require_nonempty(path)
            actual_sha = sha256(path)
            if actual_sha != expected_sha:
                raise CheckFailure(f"candidate file hash mismatch for {relative}: {actual_sha}")
        generated_patch = run(
            ["git", "diff", "--binary", f"{data['base_sha']}..{data['candidate_sha']}"], cwd=clone
        ).stdout.encode()
        if generated_patch != patch_path.read_bytes():
            raise CheckFailure("integration.patch is not the exact candidate diff")
        run(["git", "diff", "--check", f"{data['base_sha']}..{data['candidate_sha']}"], cwd=clone)
        test = run(
            [sys.executable, "-m", "unittest", "-v", "tests.test_fleet_wave"],
            cwd=clone,
            timeout=420,
        )
        if "Ran 38 tests" not in test.stderr + test.stdout or "OK" not in test.stderr + test.stdout:
            raise CheckFailure("fresh candidate test replay did not prove 38/38 tests passed")

    print(
        "EXECUTED_CHECK=PASS exact six-file Fleet Wave candidate, one-commit ancestry, "
        "bundle integrity, patch identity, and fresh 38/38 controller tests verified"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CheckFailure, OSError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"EXECUTED_CHECK=FAIL {exc}", file=sys.stderr)
        raise SystemExit(1)
