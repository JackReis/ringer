#!/usr/bin/env python3
"""Verify a completed Ringer run from immutable state JSON and eval JSONL."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "1.0"
PASS_VERDICT = "PASS"
PASS_STATUS = "pass"
FINISHED_STATE = "finished"
EXECUTED_CHECK = "executed-check"
RETRY_VERDICTS = {"FAIL", "TIMEOUT"}


JsonObject = dict[str, Any]


@dataclass(frozen=True)
class EvalRow:
    """A parsed eval-log row with its append-only line number."""

    line: int
    row: JsonObject
    task_key: str | None


def _issue(
    code: str,
    message: str,
    *,
    task_key: str | None = None,
    task_index: int | None = None,
    field: str | None = None,
    line: int | None = None,
) -> JsonObject:
    """Create a stable, sanitized validation issue."""

    item: JsonObject = {"code": code, "message": message}
    if task_key is not None:
        item["task_key"] = task_key
    if task_index is not None:
        item["task_index"] = task_index
    if field is not None:
        item["field"] = field
    if line is not None:
        item["line"] = line
    return item


def _sort_issues(issues: Iterable[JsonObject]) -> list[JsonObject]:
    """Return issues in deterministic order."""

    return sorted(
        issues,
        key=lambda item: (
            str(item.get("code", "")),
            str(item.get("task_key", "")),
            int(item.get("task_index", -1)),
            int(item.get("line", -1)),
            str(item.get("field", "")),
            str(item.get("message", "")),
        ),
    )


def _read_json_object(path: Path) -> tuple[JsonObject | None, list[JsonObject]]:
    """Read a JSON file and require a top-level object."""

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None, [
            _issue("state_read_error", "State file could not be read.")
        ]

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None, [
            _issue("state_json_malformed", "State file is not valid JSON.")
        ]

    if not isinstance(value, dict):
        return None, [
            _issue("state_not_object", "State JSON must be an object.")
        ]
    return value, []


def _coerce_key(value: Any) -> str | None:
    """Return a nonempty string key, or None when absent/invalid."""

    if isinstance(value, str) and value:
        return value
    return None


def _task_key(task: Mapping[str, Any]) -> str | None:
    """Resolve a task key from supported state task fields."""

    return _coerce_key(task.get("key")) or _coerce_key(task.get("task_key"))


def _eval_task_key(row: Mapping[str, Any]) -> str | None:
    """Resolve a task key from supported eval-log row fields."""

    return _coerce_key(row.get("task_key")) or _coerce_key(row.get("key"))


def _parse_eval_log(
    path: Path,
    expected_run_id: Any,
    known_task_keys: set[str],
) -> tuple[list[EvalRow], list[JsonObject]]:
    """Parse eval JSONL rows and validate run/task identity."""

    rows: list[EvalRow] = []
    errors: list[JsonObject] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    errors.append(
                        _issue(
                            "eval_jsonl_malformed",
                            f"Eval log has malformed JSON on line {line_number}.",
                            line=line_number,
                        )
                    )
                    continue
                if not isinstance(value, dict):
                    errors.append(
                        _issue(
                            "eval_row_not_object",
                            "Eval log row must be an object.",
                            line=line_number,
                        )
                    )
                    continue

                if "run_id" not in value:
                    errors.append(
                        _issue(
                            "missing_field",
                            "Eval log row is missing a required field.",
                            field="run_id",
                            line=line_number,
                        )
                    )
                    continue
                if expected_run_id is not None and value.get("run_id") != expected_run_id:
                    # The production eval log is append-only and shared by every
                    # Ringer run. Unrelated, otherwise well-formed rows are not
                    # evidence about the run being verified.
                    continue

                key = _eval_task_key(value)
                if key is None:
                    errors.append(
                        _issue(
                            "missing_field",
                            "Eval log row is missing a required task key.",
                            field="task_key",
                            line=line_number,
                        )
                    )
                    continue
                if known_task_keys and key not in known_task_keys:
                    errors.append(
                        _issue(
                            "eval_unknown_task",
                            "Eval log row references a task not declared in state.",
                            line=line_number,
                        )
                    )
                    continue

                for field in ("verdict", "verify_method"):
                    if field not in value:
                        errors.append(
                            _issue(
                                "missing_field",
                                "Eval log row is missing a required field.",
                                task_key=key,
                                field=field,
                                line=line_number,
                            )
                        )

                rows.append(EvalRow(line=line_number, row=value, task_key=key))
    except (OSError, UnicodeDecodeError):
        errors.append(_issue("eval_log_read_error", "Eval log file could not be read."))

    return rows, errors


def _require_fields(
    obj: Mapping[str, Any],
    fields: Sequence[str],
    errors: list[JsonObject],
    *,
    message: str,
    task_key: str | None = None,
    task_index: int | None = None,
) -> None:
    """Append missing-field errors for absent keys."""

    for field in fields:
        if field not in obj:
            errors.append(
                _issue(
                    "missing_field",
                    message,
                    task_key=task_key,
                    task_index=task_index,
                    field=field,
                )
            )


def _is_int(value: Any) -> bool:
    """Return true for ints, excluding bool."""

    return isinstance(value, int) and not isinstance(value, bool)


def _is_zero_number(value: Any) -> bool:
    """Return true for numeric zero, excluding bool."""

    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value == 0
    )


def _declared_deliverables(
    task: Mapping[str, Any],
    task_key: str,
    task_index: int,
) -> tuple[list[str], list[JsonObject]]:
    """Extract declared deliverable paths from supported task fields."""

    errors: list[JsonObject] = []
    paths: list[str] = []

    def add_path(value: Any, field: str) -> None:
        if isinstance(value, str) and value:
            paths.append(value)
            return
        errors.append(
            _issue(
                "deliverable_path_invalid",
                "Declared deliverable path must be a nonempty string.",
                task_key=task_key,
                task_index=task_index,
                field=field,
            )
        )

    if "deliverable_path" in task:
        add_path(task["deliverable_path"], "deliverable_path")

    for field in ("deliverables", "deliverable_paths"):
        if field not in task:
            continue
        value = task[field]
        if not isinstance(value, list):
            errors.append(
                _issue(
                    "deliverables_invalid",
                    "Declared deliverables must be a list.",
                    task_key=task_key,
                    task_index=task_index,
                    field=field,
                )
            )
            continue
        for entry in value:
            if isinstance(entry, str):
                add_path(entry, field)
            elif isinstance(entry, dict):
                add_path(entry.get("path"), field)
            else:
                errors.append(
                    _issue(
                        "deliverable_path_invalid",
                        "Declared deliverable path must be a nonempty string.",
                        task_key=task_key,
                        task_index=task_index,
                        field=field,
                    )
                )

    return paths, errors


def _path_exists(path_text: str, base_dir: Path) -> bool:
    """Check path existence without reading file contents."""

    try:
        path = Path(path_text)
        if not path.is_absolute():
            path = base_dir / path
        return path.exists()
    except (OSError, ValueError):
        return False


def _empty_report(run_id: Any = None) -> JsonObject:
    """Create an empty deterministic report skeleton."""

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id if isinstance(run_id, str) else None,
        "valid": False,
        "errors": [],
        "warnings": [],
        "summary": {
            "deliverables_checked": False,
            "deliverables_missing": 0,
            "deliverables_total": 0,
            "eval_matching_rows_total": 0,
            "eval_rows_total": 0,
            "retries_total": 0,
            "state_summary_fail": None,
            "tasks_total": 0,
        },
        "per_task": [],
    }


def verify_run(
    state_path: str | Path,
    eval_log_path: str | Path,
    *,
    require_deliverables: bool = False,
) -> JsonObject:
    """Validate a Ringer state JSON file and append-only eval JSONL log."""

    state_file = Path(state_path)
    eval_file = Path(eval_log_path)
    report = _empty_report()
    errors: list[JsonObject] = []
    warnings: list[JsonObject] = []

    state, state_errors = _read_json_object(state_file)
    errors.extend(state_errors)
    if state is None:
        report["errors"] = _sort_issues(errors)
        report["warnings"] = _sort_issues(warnings)
        return report

    run_id = state.get("run_id")
    report["run_id"] = run_id if isinstance(run_id, str) else None
    _require_fields(
        state,
        ("run_id", "finished", "state", "summary", "tasks"),
        errors,
        message="State is missing a required field.",
    )
    if "run_id" in state and not isinstance(run_id, str):
        errors.append(
            _issue("run_id_invalid", "State run_id must be a string.", field="run_id")
        )
    if "finished" in state and state.get("finished") is not True:
        errors.append(
            _issue(
                "state_finished_not_true",
                "State finished flag must be true.",
                field="finished",
            )
        )
    if "state" in state and state.get("state") != FINISHED_STATE:
        errors.append(
            _issue(
                "state_state_not_finished",
                "State lifecycle value must be finished.",
                field="state",
            )
        )

    summary_value = state.get("summary")
    summary_fail: Any = None
    if not isinstance(summary_value, dict):
        if "summary" in state:
            errors.append(
                _issue("summary_invalid", "State summary must be an object.", field="summary")
            )
    else:
        summary_fail = summary_value.get("fail")
        if "fail" not in summary_value:
            errors.append(
                _issue(
                    "missing_field",
                    "State summary is missing a required field.",
                    field="summary.fail",
                )
            )
        elif not _is_zero_number(summary_fail):
            errors.append(
                _issue(
                    "summary_fail_nonzero",
                    "State summary fail count must be zero.",
                    field="summary.fail",
                )
            )

    tasks_value = state.get("tasks")
    tasks: list[JsonObject] = []
    if not isinstance(tasks_value, list):
        if "tasks" in state:
            errors.append(_issue("tasks_invalid", "State tasks must be a list.", field="tasks"))
    elif not tasks_value:
        errors.append(_issue("tasks_empty", "State tasks must be a nonempty list.", field="tasks"))
    else:
        for index, value in enumerate(tasks_value):
            if isinstance(value, dict):
                tasks.append(value)
            else:
                errors.append(
                    _issue(
                        "task_invalid",
                        "State task entry must be an object.",
                        task_index=index,
                    )
                )

    task_by_key: dict[str, JsonObject] = {}
    task_indexes: dict[str, int] = {}
    task_errors_by_key: dict[str, list[JsonObject]] = {}
    deliverables_by_key: dict[str, list[str]] = {}

    for index, task in enumerate(tasks):
        key = _task_key(task)
        if key is None:
            errors.append(
                _issue(
                    "missing_field",
                    "State task is missing a required task key.",
                    task_index=index,
                    field="key",
                )
            )
            continue
        if key in task_by_key:
            errors.append(
                _issue(
                    "duplicate_task_key",
                    "State tasks must not contain duplicate task keys.",
                    task_key=key,
                    task_index=index,
                    field="key",
                )
            )
            continue

        task_by_key[key] = task
        task_indexes[key] = index
        task_errors_by_key[key] = []
        _require_fields(
            task,
            (
                "status",
                "verdict",
                "check_returncode",
                "check_timed_out",
                "attempts",
            ),
            errors,
            message="State task is missing a required field.",
            task_key=key,
            task_index=index,
        )

        if "status" in task and task.get("status") != PASS_STATUS:
            errors.append(
                _issue(
                    "task_status_not_pass",
                    "State task status must be pass.",
                    task_key=key,
                    task_index=index,
                    field="status",
                )
            )
        if "verdict" in task and task.get("verdict") != PASS_VERDICT:
            errors.append(
                _issue(
                    "task_verdict_not_pass",
                    "State task verdict must be PASS.",
                    task_key=key,
                    task_index=index,
                    field="verdict",
                )
            )
        if "check_returncode" in task and (
            not _is_int(task.get("check_returncode")) or task.get("check_returncode") != 0
        ):
            errors.append(
                _issue(
                    "task_check_returncode_nonzero",
                    "State task check_returncode must be zero.",
                    task_key=key,
                    task_index=index,
                    field="check_returncode",
                )
            )
        if "check_timed_out" in task and task.get("check_timed_out") is not False:
            errors.append(
                _issue(
                    "task_check_timed_out",
                    "State task check_timed_out must be false.",
                    task_key=key,
                    task_index=index,
                    field="check_timed_out",
                )
            )
        attempts = task.get("attempts")
        if "attempts" in task and (not _is_int(attempts) or attempts < 1):
            errors.append(
                _issue(
                    "task_attempts_invalid",
                    "State task attempts must be an integer greater than or equal to one.",
                    task_key=key,
                    task_index=index,
                    field="attempts",
                )
            )

        deliverables, deliverable_errors = _declared_deliverables(task, key, index)
        deliverables_by_key[key] = deliverables
        errors.extend(deliverable_errors)

    eval_rows, eval_errors = _parse_eval_log(
        eval_file,
        run_id if isinstance(run_id, str) else None,
        set(task_by_key),
    )
    errors.extend(eval_errors)

    rows_by_task: dict[str, list[EvalRow]] = {key: [] for key in task_by_key}
    for eval_row in eval_rows:
        if eval_row.task_key in rows_by_task:
            rows_by_task[eval_row.task_key].append(eval_row)

    per_task: list[JsonObject] = []
    retries_total = 0
    matching_rows_total = 0
    deliverables_total = 0
    deliverables_missing = 0

    for key in sorted(task_by_key):
        task = task_by_key[key]
        index = task_indexes[key]
        matching_rows = rows_by_task.get(key, [])
        matching_rows_total += len(matching_rows)
        retry_count = sum(
            1 for row in matching_rows[:-1] if row.row.get("verdict") in RETRY_VERDICTS
        )
        retries_total += retry_count

        latest_line: int | None = None
        latest_verdict: str | None = None
        latest_method: str | None = None
        if not matching_rows:
            errors.append(
                _issue(
                    "eval_missing_for_task",
                    "Eval log must contain at least one matching row for each task.",
                    task_key=key,
                    task_index=index,
                )
            )
        else:
            latest = matching_rows[-1]
            latest_line = latest.line
            verdict = latest.row.get("verdict")
            method = latest.row.get("verify_method")
            latest_verdict = verdict if isinstance(verdict, str) else None
            latest_method = method if isinstance(method, str) else None
            if verdict != PASS_VERDICT:
                errors.append(
                    _issue(
                        "latest_eval_not_pass",
                        "Latest eval row for task must have verdict PASS.",
                        task_key=key,
                        task_index=index,
                        field="verdict",
                        line=latest.line,
                    )
                )
            if method != EXECUTED_CHECK:
                errors.append(
                    _issue(
                        "latest_eval_method_invalid",
                        "Latest eval row for task must use verify_method executed-check.",
                        task_key=key,
                        task_index=index,
                        field="verify_method",
                        line=latest.line,
                    )
                )

        declared = deliverables_by_key.get(key, [])
        deliverables_total += len(declared)
        missing_for_task = 0
        if require_deliverables:
            for path_text in declared:
                if not _path_exists(path_text, state_file.parent):
                    missing_for_task += 1
                    deliverables_missing += 1
            if missing_for_task:
                errors.append(
                    _issue(
                        "deliverable_missing",
                        "One or more declared deliverable paths do not exist.",
                        task_key=key,
                        task_index=index,
                    )
                )

        per_task.append(
            {
                "attempts": task.get("attempts") if _is_int(task.get("attempts")) else None,
                "deliverables_declared": len(declared),
                "deliverables_missing": missing_for_task,
                "eval_matches": len(matching_rows),
                "key": key,
                "latest_eval_executed_check": latest_method == EXECUTED_CHECK
                if latest_method is not None
                else None,
                "latest_eval_line": latest_line,
                "latest_eval_pass": latest_verdict == PASS_VERDICT
                if latest_verdict is not None
                else None,
                "retries": retry_count,
                "state_check_returncode": task.get("check_returncode")
                if _is_int(task.get("check_returncode"))
                else None,
                "state_check_timed_out": task.get("check_timed_out")
                if isinstance(task.get("check_timed_out"), bool)
                else None,
                "state_status_pass": task.get("status") == PASS_STATUS
                if "status" in task
                else None,
                "state_verdict_pass": task.get("verdict") == PASS_VERDICT
                if "verdict" in task
                else None,
                "valid": True,
            }
        )

    invalid_task_keys = {
        str(item["task_key"]) for item in errors if isinstance(item.get("task_key"), str)
    }
    for item in per_task:
        item["valid"] = item["key"] not in invalid_task_keys

    report["summary"] = {
        "deliverables_checked": require_deliverables,
        "deliverables_missing": deliverables_missing,
        "deliverables_total": deliverables_total,
        "eval_matching_rows_total": matching_rows_total,
        "eval_rows_total": len(eval_rows),
        "retries_total": retries_total,
        "state_summary_fail": summary_fail if _is_zero_number(summary_fail) else None,
        "tasks_total": len(task_by_key),
    }
    report["per_task"] = per_task
    report["errors"] = _sort_issues(errors)
    report["warnings"] = _sort_issues(warnings)
    report["valid"] = not report["errors"]
    return report


def write_json_atomic(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Write JSON atomically, creating the parent directory if needed."""

    output_path = Path(path)
    parent = output_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True, separators=(",", ": "))
    encoded += "\n"

    fd = -1
    tmp_name = ""
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=str(parent),
            text=True,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, output_path)
    finally:
        if fd >= 0:
            os.close(fd)
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Verify a Ringer run state JSON object against eval JSONL rows."
    )
    parser.add_argument("--state", required=True, help="Path to immutable Ringer state JSON.")
    parser.add_argument("--eval-log", required=True, help="Path to append-only eval JSONL.")
    parser.add_argument("--output", required=True, help="Path to write verification JSON.")
    parser.add_argument(
        "--require-deliverables",
        action="store_true",
        help="Require every declared deliverable path to exist.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the verifier CLI."""

    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        report = verify_run(
            args.state,
            args.eval_log,
            require_deliverables=bool(args.require_deliverables),
        )
        write_json_atomic(args.output, report)
    except Exception:
        fallback = _empty_report()
        fallback["errors"] = [
            _issue("output_write_error", "Verification output could not be written.")
        ]
        try:
            write_json_atomic(args.output, fallback)
        except Exception:
            sys.stderr.write("verification failed before output could be written\n")
        return 1

    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
