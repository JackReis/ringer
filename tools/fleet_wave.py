#!/usr/bin/env python3
"""Fail-closed controller for a versioned Fleet Wave protocol (stdlib only)."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ProtocolError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProtocolError(f"{path} must contain a JSON object")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_receipt(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(argv: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True)
    except OSError as exc:
        raise ProtocolError(f"could not execute {argv[0]}: {exc}") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise ProtocolError(f"command failed ({' '.join(argv)}): {detail}")
    return result


def resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


WORK_TYPES = {"code", "deployment", "config", "factual-research", "other"}
STRONG_CHECK_PATTERNS = {
    "code": r"(?:^|&&|\|\||;)\s*(?:(?:python\d*(?:\.\d+)?\s+-m\s+)(?:pytest|unittest|compileall)|pytest\b|npm\s+(?:test|run\s+test)\b|cargo\s+test\b|go\s+test\b)",
    "deployment": r"(?:^|&&|\|\||;)\s*(?:curl\b|systemctl\b|launchctl\b|kubectl\b|docker\b)",
    "config": r"(?:^|&&|\|\||;)\s*(?:python\d*(?:\.\d+)?\b[^;&|]*(?:json\.load|tomllib|configparser)|plutil\b|jq\b)",
}


def validate_version_chain(manifest: dict[str, Any], path: Path) -> None:
    version = manifest["manifest_version"]
    match = re.fullmatch(r"manifest-v(\d+)\.json", path.name)
    if not match or int(match.group(1)) != version:
        raise ProtocolError(f"manifest filename must be manifest-v{version}.json")
    supersedes = manifest.get("supersedes")
    if version == 1:
        if supersedes is not None:
            raise ProtocolError("manifest-v1.json must not supersede another manifest")
        return
    if not isinstance(supersedes, str) or not supersedes:
        raise ProtocolError("manifest-vN requires supersedes when N > 1")
    prior_path = resolve(path.parent, supersedes).resolve()
    expected = path.with_name(f"manifest-v{version - 1}.json").resolve()
    if prior_path != expected or not prior_path.is_file():
        raise ProtocolError(f"supersedes must reference existing manifest-v{version - 1}.json")
    prior = load(prior_path)
    if prior.get("wave_id") != manifest["wave_id"] or prior.get("manifest_version") != version - 1:
        raise ProtocolError("superseded manifest is not the preceding version of this wave")


def check_is_strong(work_type: str, check: str, evidence_kind: str) -> bool:
    if work_type == "factual-research":
        return evidence_kind == "judgmental"
    pattern = STRONG_CHECK_PATTERNS.get(work_type)
    return bool(pattern and re.search(pattern, check, re.IGNORECASE))


def validate_manifest(manifest: dict[str, Any], path: Path) -> Path:
    required = {"schema_version", "manifest_version", "wave_id", "ringer_manifest", "beads", "tasks"}
    missing = sorted(required - manifest.keys())
    if missing:
        raise ProtocolError("missing fields: " + ", ".join(missing))
    if manifest["schema_version"] != "fleet-wave.v1":
        raise ProtocolError("schema_version must be fleet-wave.v1")
    version = manifest["manifest_version"]
    if not isinstance(version, int) or version < 1:
        raise ProtocolError("manifest_version must be a positive integer")
    validate_version_chain(manifest, path)
    beads = manifest["beads"]
    if not isinstance(beads, dict) or not beads.get("claim_id"):
        raise ProtocolError("beads.claim_id is required")
    tasks = manifest["tasks"]
    if not isinstance(tasks, list) or not tasks:
        raise ProtocolError("tasks must be a non-empty array")
    keys: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict) or not task.get("key"):
            raise ProtocolError("every task needs a key")
        if task["key"] in keys:
            raise ProtocolError(f"duplicate task key: {task['key']}")
        keys.add(task["key"])
        evidence = task.get("evidence")
        if not isinstance(evidence, dict) or evidence.get("strength") != "strong":
            raise ProtocolError(f"task {task['key']} must require strong evidence")
        if evidence.get("kind") not in {"objective", "judgmental"}:
            raise ProtocolError(f"task {task['key']} has invalid evidence kind")
    ringer_path = resolve(path.parent, str(manifest["ringer_manifest"]))
    ringer = load(ringer_path)
    ringer_keys = {t.get("key") for t in ringer.get("tasks", []) if isinstance(t, dict)}
    if keys != ringer_keys:
        raise ProtocolError("Fleet Wave task keys must exactly match Ringer task keys")
    ringer_tasks = {t["key"]: t for t in ringer.get("tasks", []) if isinstance(t, dict) and "key" in t}
    for task in tasks:
        work_type = task.get("work_type")
        if work_type not in WORK_TYPES:
            raise ProtocolError(f"task {task['key']} has invalid or missing work_type")
        if work_type != "other":
            check = ringer_tasks[task["key"]].get("check")
            if not isinstance(check, str) or not check_is_strong(work_type, check, task["evidence"]["kind"]):
                raise ProtocolError(f"task {task['key']} has only a weak check for {work_type} work")
    return ringer_path


def ids(surface: Any) -> list[str]:
    if not isinstance(surface, dict):
        return []
    existing = surface.get("existing_ids", [])
    if not isinstance(existing, list) or not all(isinstance(v, str) and v for v in existing):
        raise ProtocolError("existing_ids must be an array of non-empty strings")
    values = [surface.get("claim_id") or surface.get("issue_id"), *existing]
    return list(dict.fromkeys(str(v) for v in values if v))


def bd(args: argparse.Namespace, *parts: str) -> subprocess.CompletedProcess[str]:
    return run([args.bd_bin, *parts, "--json"])


def prepare(args: argparse.Namespace) -> None:
    path = Path(args.manifest).resolve()
    manifest = load(path)
    ringer_path = validate_manifest(manifest, path)
    degraded = False
    try:
        claim = str(manifest["beads"]["claim_id"])
        bd(args, "update", claim, "--claim")
        readback = bd(args, "show", claim)
        claimed = json.loads(readback.stdout)
        if claimed.get("status") not in {"in_progress", "claimed"} or not claimed.get("assignee"):
            raise ProtocolError("Beads claim readback did not confirm the claim")
        for bead_id in ids(manifest["beads"])[1:]:
            bd(args, "show", bead_id)
        paperclip = manifest.get("paperclip")
        if paperclip:
            if not args.paperclip_bin:
                raise ProtocolError("paperclip manifest requires --paperclip-bin for reconciliation")
            for issue_id in ids(paperclip):
                run([args.paperclip_bin, "show", issue_id])
    except (ProtocolError, json.JSONDecodeError):
        if not args.degraded_no_dispatch:
            raise
        degraded = True
    if not degraded:
        run([args.ringer_bin, "lint", str(ringer_path)])
        run([args.ringer_bin, "run", str(ringer_path), "--dry-run"])
    receipt = {
        "schema_version": "fleet-wave.v1", "event": "prepared", "prepared_at": now(),
        "wave_id": manifest["wave_id"], "manifest_version": manifest["manifest_version"],
        "manifest_sha256": digest(path), "ringer_manifest_sha256": digest(ringer_path),
        "beads_claim_id": manifest["beads"]["claim_id"],
        "degraded_no_dispatch": degraded,
        "dispatch_authorized": not degraded,
    }
    write_receipt(Path(args.receipt), receipt)


def verify_binding(manifest_path: Path, manifest: dict[str, Any], ringer_path: Path, prepared: dict[str, Any]) -> None:
    if prepared.get("event") != "prepared" or prepared.get("wave_id") != manifest["wave_id"]:
        raise ProtocolError("prepared receipt is not bound to this wave")
    if prepared.get("manifest_sha256") != digest(manifest_path):
        raise ProtocolError("manifest changed after prepare")
    if prepared.get("ringer_manifest_sha256") != digest(ringer_path):
        raise ProtocolError("Ringer manifest changed after prepare")
    if not prepared.get("dispatch_authorized"):
        raise ProtocolError("degraded receipt cannot authorize post-run")


def post_run(args: argparse.Namespace) -> None:
    path = Path(args.manifest).resolve()
    manifest = load(path)
    ringer_path = validate_manifest(manifest, path)
    prepared_path = Path(args.prepared_receipt)
    prepared = load(prepared_path)
    verify_binding(path, manifest, ringer_path, prepared)
    state_path = Path(args.run_state)
    state = load(state_path)
    if str(state.get("verdict", "")).lower() not in {"pass", "passed"}:
        raise ProtocolError("Ringer verdict is not pass")
    task_verdicts = {t.get("key"): str(t.get("verdict", "")).lower() for t in state.get("tasks", [])}
    ringer = load(ringer_path)
    workdir = resolve(ringer_path.parent, str(ringer.get("workdir", ".")))
    replay: dict[str, bool] = {}
    for task in ringer["tasks"]:
        key = task["key"]
        if task_verdicts.get(key) not in {"pass", "passed"}:
            raise ProtocolError(f"Ringer task verdict is not pass: {key}")
        taskdir = workdir / key
        for expected in task.get("expect_files", []):
            item = taskdir / expected
            if not item.is_file() or item.stat().st_size == 0:
                raise ProtocolError(f"independent replay missing evidence: {key}/{expected}")
        run(["/bin/sh", "-c", str(task["check"])], cwd=taskdir)
        replay[key] = True
    judgmental = any(t["evidence"]["kind"] == "judgmental" for t in manifest["tasks"])
    judge_hash = None
    if judgmental:
        if not args.judge_receipt:
            raise ProtocolError("judgmental tasks require a fresh judge receipt")
        judge_path = Path(args.judge_receipt)
        judge = load(judge_path)
        if judge.get("wave_id") != manifest["wave_id"] or judge.get("manifest_sha256") != digest(path):
            raise ProtocolError("judge receipt is not hash-bound to this wave")
        if str(judge.get("verdict", "")).lower() not in {"pass", "passed"}:
            raise ProtocolError("judge verdict is not pass")
        try:
            judged_at = datetime.fromisoformat(str(judge["judged_at"]).replace("Z", "+00:00"))
            prepared_at = datetime.fromisoformat(str(prepared["prepared_at"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError("judge receipt has an invalid timestamp") from exc
        if judged_at.tzinfo is None or prepared_at.tzinfo is None or judged_at <= prepared_at:
            raise ProtocolError("judge receipt is stale")
        judge_hash = digest(judge_path)
    receipt = {
        "schema_version": "fleet-wave.v1", "event": "post-run", "completed_at": now(),
        "wave_id": manifest["wave_id"], "manifest_sha256": digest(path),
        "prepared_receipt_sha256": digest(prepared_path), "run_state_sha256": digest(state_path),
        "ringer_verdict": "pass", "independent_replay": replay, "judge_receipt_sha256": judge_hash,
    }
    # Canonical authority first. Any Beads failure aborts before visibility projection.
    summary = json.dumps(receipt, sort_keys=True)
    for bead_id in ids(manifest["beads"]):
        bd(args, "comments", "add", bead_id, summary)
    paperclip = manifest.get("paperclip")
    if paperclip and args.paperclip_bin:
        for issue_id in ids(paperclip):
            run([args.paperclip_bin, "comment", issue_id, summary])
    write_receipt(Path(args.receipt), receipt)


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("manifest")
    common.add_argument("--bd-bin", required=True)
    common.add_argument("--ringer-bin", required=True)
    common.add_argument("--paperclip-bin")
    common.add_argument("--receipt", required=True)
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    pre = commands.add_parser("prepare", parents=[common])
    pre.add_argument("--degraded-no-dispatch", action="store_true")
    post = commands.add_parser("post-run", parents=[common])
    post.add_argument("--prepared-receipt", required=True)
    post.add_argument("--run-state", required=True)
    post.add_argument("--judge-receipt")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        (prepare if args.command == "prepare" else post_run)(args)
    except ProtocolError as exc:
        print(f"fleet-wave: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
