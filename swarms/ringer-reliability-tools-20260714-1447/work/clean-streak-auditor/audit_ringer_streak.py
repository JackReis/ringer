#!/usr/bin/env python3
"""Audit recent Ringer run states for a clean contiguous streak."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


ERROR_ORDER = {
    "states_dir_unreadable": 10,
    "eval_log_unreadable": 20,
    "invalid_state_json": 30,
    "invalid_eval_json": 40,
    "invalid_required_count": 50,
    "no_selected_runs": 60,
    "insufficient_runs": 70,
    "duplicate_run_id": 80,
    "missing_run_id": 90,
    "malformed_timestamp": 100,
    "duplicate_task_key": 110,
    "task_key_missing": 120,
    "latest_window_not_clean": 130,
    "run_unfinished": 140,
    "summary_fail_nonzero": 150,
    "no_tasks": 160,
    "task_verdict_not_pass": 170,
    "task_status_not_pass": 180,
    "task_check_returncode_nonzero": 190,
    "task_check_timed_out": 200,
    "task_attempts_not_one": 210,
    "missing_eval_row": 220,
    "eval_missing": 230,
    "eval_verdict_not_pass": 240,
    "eval_retry_true": 250,
}


@dataclass(frozen=True)
class RunRecord:
    """Parsed state data needed for redacted audit output."""

    run_id: str
    run_name: str
    started_at: str | None
    sort_key: tuple[datetime, str]
    state: dict[str, Any]


def ordered_codes(codes: Iterable[str]) -> list[str]:
    """Return deterministic, de-duplicated reason codes."""
    unique = set(codes)
    return sorted(unique, key=lambda code: (ERROR_ORDER.get(code, 10_000), code))


def parse_timestamp(value: Any) -> tuple[datetime, str] | None:
    """Parse an ISO-like timestamp into a deterministic sort key."""
    if not isinstance(value, str) or not value:
        return None
    normalized = value
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc), value


def task_key(task: dict[str, Any]) -> str | None:
    """Extract a stable task key from supported task/eval row shapes."""
    for field in ("task_key", "key", "task_id", "id"):
        value = task.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def read_state_objects(states_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Read top-level JSON state files from a directory."""
    errors: list[str] = []
    states: list[dict[str, Any]] = []
    try:
        paths = sorted(states_dir.iterdir(), key=lambda path: path.name)
    except OSError:
        return [], ["states_dir_unreadable"]
    if not states_dir.is_dir():
        return [], ["states_dir_unreadable"]
    for path in paths:
        if path.suffix.lower() != ".json" or path.is_symlink() or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            errors.append("invalid_state_json")
            continue
        if not isinstance(data, dict):
            errors.append("invalid_state_json")
            continue
        states.append(data)
    return states, ordered_codes(errors)


def read_latest_eval_rows(eval_log: Path) -> tuple[dict[tuple[str, str], dict[str, Any]], list[str]]:
    """Read eval JSONL and keep the latest row for each run/task pair."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    errors: list[str] = []
    try:
        handle = eval_log.open("r", encoding="utf-8")
    except OSError:
        return latest, ["eval_log_unreadable"]
    with handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                errors.append("invalid_eval_json")
                continue
            if not isinstance(row, dict):
                errors.append("invalid_eval_json")
                continue
            run_id = row.get("run_id")
            key = task_key(row)
            if not isinstance(run_id, str) or not run_id or key is None:
                errors.append("invalid_eval_json")
                continue
            latest[(run_id, key)] = row
    return latest, ordered_codes(errors)


def selected_records(states: list[dict[str, Any]], run_prefix: str) -> tuple[list[RunRecord], int, list[str]]:
    """Select matching states, rejecting duplicate IDs and malformed timestamps."""
    records: list[RunRecord] = []
    errors: list[str] = []
    seen_run_ids: set[str] = set()
    selected_count = 0
    for state in states:
        run_name = state.get("run_name")
        if not isinstance(run_name, str) or not run_name.startswith(run_prefix):
            continue
        selected_count += 1
        run_id = state.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            errors.append("missing_run_id")
            continue
        if run_id in seen_run_ids:
            errors.append("duplicate_run_id")
        seen_run_ids.add(run_id)
        parsed_timestamp = parse_timestamp(state.get("started_at"))
        if parsed_timestamp is None:
            errors.append("malformed_timestamp")
            continue
        sort_datetime, started_at = parsed_timestamp
        records.append(
            RunRecord(
                run_id=run_id,
                run_name=run_name,
                started_at=started_at,
                sort_key=(sort_datetime, run_id),
                state=state,
            )
        )
    records.sort(key=lambda record: record.sort_key)
    return records, selected_count, ordered_codes(errors)


def evaluate_run(record: RunRecord, latest_eval_rows: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    """Evaluate one run and return only redacted, deterministic fields."""
    reasons: list[str] = []
    state = record.state
    if state.get("finished") is not True:
        reasons.append("run_unfinished")
    summary = state.get("summary")
    fail_count = summary.get("fail") if isinstance(summary, dict) else None
    if fail_count != 0:
        reasons.append("summary_fail_nonzero")
    tasks_raw = state.get("tasks")
    tasks = tasks_raw if isinstance(tasks_raw, list) else []
    if not tasks:
        reasons.append("no_tasks")
    seen_task_keys: set[str] = set()
    duplicate_task = False
    missing_task_key = False
    for task_raw in tasks:
        if not isinstance(task_raw, dict):
            reasons.append("task_key_missing")
            missing_task_key = True
            continue
        key = task_key(task_raw)
        if key is None:
            reasons.append("task_key_missing")
            missing_task_key = True
        elif key in seen_task_keys:
            reasons.append("duplicate_task_key")
            duplicate_task = True
        else:
            seen_task_keys.add(key)
        if task_raw.get("verdict") != "PASS":
            reasons.append("task_verdict_not_pass")
        if task_raw.get("status") != "pass":
            reasons.append("task_status_not_pass")
        if task_raw.get("check_returncode") != 0:
            reasons.append("task_check_returncode_nonzero")
        if task_raw.get("check_timed_out") is not False:
            reasons.append("task_check_timed_out")
        attempts = task_raw.get("attempts")
        if not (isinstance(attempts, int) and not isinstance(attempts, bool) and attempts == 1):
            reasons.append("task_attempts_not_one")
        if key is None:
            continue
        eval_row = latest_eval_rows.get((record.run_id, key))
        if eval_row is None:
            reasons.append("eval_missing")
            continue
        if eval_row.get("verdict") != "PASS":
            reasons.append("eval_verdict_not_pass")
        if eval_row.get("retry") is not False:
            reasons.append("eval_retry_true")
    ordered_reasons = ordered_codes(reasons)
    if duplicate_task:
        ordered_reasons = ordered_codes([*ordered_reasons, "duplicate_task_key"])
    if missing_task_key:
        ordered_reasons = ordered_codes([*ordered_reasons, "task_key_missing"])
    return {
        "run_id": record.run_id,
        "started_at": record.started_at,
        "clean": not ordered_reasons,
        "task_count": len(tasks),
        "reasons": ordered_reasons,
    }


def latest_window_errors(window_runs: list[dict[str, Any]]) -> list[str]:
    """Return global error codes implied by dirty runs in the accepted window."""
    errors: list[str] = []
    for run in window_runs:
        for reason in run["reasons"]:
            if reason == "eval_missing":
                errors.append("missing_eval_row")
            else:
                errors.append(reason)
    if any(not run["clean"] for run in window_runs):
        errors.append("latest_window_not_clean")
    return ordered_codes(errors)


def audit(
    states_dir: str | os.PathLike[str],
    eval_log: str | os.PathLike[str],
    run_prefix: str,
    required_count: int,
) -> dict[str, Any]:
    """Audit state and eval files and return redacted JSON-ready data."""
    errors: list[str] = []
    states, state_errors = read_state_objects(Path(states_dir))
    latest_eval_rows, eval_errors = read_latest_eval_rows(Path(eval_log))
    errors.extend(state_errors)
    errors.extend(eval_errors)
    if required_count < 1:
        errors.append("invalid_required_count")
    records, selected_count, selection_errors = selected_records(states, run_prefix)
    errors.extend(selection_errors)
    run_entries = [evaluate_run(record, latest_eval_rows) for record in records]
    if selected_count == 0:
        errors.append("no_selected_runs")
    if required_count > 0 and len(run_entries) < required_count:
        errors.append("insufficient_runs")
    if required_count > 0 and len(run_entries) >= required_count:
        latest_runs = run_entries[-required_count:]
    else:
        latest_runs = run_entries
    errors.extend(latest_window_errors(latest_runs))
    if any("duplicate_task_key" in run["reasons"] for run in run_entries):
        errors.append("duplicate_task_key")
    if any("task_key_missing" in run["reasons"] for run in run_entries):
        errors.append("task_key_missing")
    clean_count = sum(1 for run in latest_runs if run["clean"])
    ordered_errors = ordered_codes(errors)
    valid = (
        required_count > 0
        and selected_count >= required_count
        and clean_count == required_count
        and not ordered_errors
    )
    return {
        "valid": valid,
        "prefix": run_prefix,
        "required_count": required_count,
        "selected_count": selected_count,
        "clean_count": clean_count,
        "errors": ordered_errors,
        "runs": run_entries,
    }


def write_json_atomic(output_path: str | os.PathLike[str], data: dict[str, Any]) -> None:
    """Write deterministic JSON atomically, creating parent directories."""
    path = Path(output_path)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=False, separators=(",", ": ")) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(description="Audit a Ringer clean-run streak.")
    parser.add_argument("--states-dir", required=True)
    parser.add_argument("--eval-log", required=True)
    parser.add_argument("--run-prefix", required=True)
    parser.add_argument("--required-count", required=True, type=int)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI without exposing tracebacks for bad inputs."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        data = audit(args.states_dir, args.eval_log, args.run_prefix, args.required_count)
        write_json_atomic(args.output, data)
    except Exception as exc:
        sys.stderr.write(f"audit_ringer_streak: {exc.__class__.__name__}\n")
        return 2
    return 0 if data["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
