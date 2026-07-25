#!/usr/bin/env python3
"""Validate a self-contained Ringer manifest without importing Ringer."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal


Severity = Literal["error", "warning"]

SAFE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
PATH_LIKE_RE = re.compile(
    r"(?:^|\s)(?:\.{0,2}/)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*"
    r"\.(?:md|txt|json|ya?ml|py|sh|rst)(?:\b|$)",
    re.IGNORECASE,
)
PROHIBITED_ROUTE = "".join(("t", "e", "r", "r", "a"))

TOP_LEVEL_KEYS = {
    "schema_version",
    "run_name",
    "workdir",
    "max_parallel",
    "worktrees",
    "default_engine",
    "tasks",
}
TASK_KEYS = {
    "key",
    "task_type",
    "engine",
    "model",
    "provider",
    "spec",
    "timeout_s",
    "check",
    "expect_files",
    "verified",
}


class DuplicateTrackingDict(dict[str, Any]):
    """Dictionary subclass that preserves duplicate JSON key metadata."""

    def __init__(self, pairs: Iterable[tuple[str, Any]]) -> None:
        super().__init__()
        self.duplicate_keys: list[str] = []
        for key, value in pairs:
            if key in self:
                self.duplicate_keys.append(key)
            self[key] = value


@dataclass(frozen=True)
class Finding:
    """A stable, redacted validation finding."""

    severity: Severity
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        """Return a JSON-serializable finding."""
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


def _finding(severity: Severity, code: str, path: str, message: str) -> Finding:
    return Finding(severity=severity, code=code, path=path, message=message)


def _child_path(path: str, key: str) -> str:
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        return f"{path}.{key}"
    return f"{path}[{json.dumps(key, ensure_ascii=True)}]"


def _index_path(path: str, index: int) -> str:
    return f"{path}[{index}]"


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_safe_slug(value: Any) -> bool:
    return isinstance(value, str) and bool(SAFE_SLUG_RE.fullmatch(value))


def _has_prohibited_route(value: str) -> bool:
    return PROHIBITED_ROUTE.casefold() in value.casefold()


def _is_safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if "\x00" in value or "\\" in value:
        return False
    if value.startswith("/") or value.startswith("~"):
        return False
    if len(value) >= 2 and value[1] == ":":
        return False
    if not SAFE_PATH_RE.fullmatch(value):
        return False
    return all(part not in {"", ".", ".."} for part in value.split("/"))


def _has_fail_fast(check: str) -> bool:
    fail_fast_patterns = (
        r"(^|[;\n]\s*)set\s+-[A-Za-z]*e[A-Za-z]*\b",
        r"(^|[;\n]\s*)set\s+-o\s+errexit\b",
        r"\|\|\s*(?:exit|return)\b",
        r"\b(?:python|python3)\b.*\b-m\s+pytest\b.*\s-x\b",
        r"\bpytest\b.*\s-x\b",
        r"\braise\s+SystemExit\b",
        r"\bsys\.exit\s*\(",
    )
    if "&&" in check:
        return True
    return any(re.search(pattern, check) for pattern in fail_fast_patterns)


def _has_pass_marker(check: str) -> bool:
    return re.search(r"\bPASS\b", check) is not None


def _is_pointer_only_spec(spec: str) -> bool:
    if not PATH_LIKE_RE.search(spec):
        return False
    scrubbed = PATH_LIKE_RE.sub(" ", spec.casefold())
    scrubbed = re.sub(
        r"\b(?:see|refer|read|consult|follow|use|file|doc|document|"
        r"instructions?|full|details?|task|spec|implementation|another|"
        r"please|only|the|a|an|and|or|to|for|from|in|at|of|with|as|is|are)\b",
        " ",
        scrubbed,
    )
    tokens = re.findall(r"[a-z0-9]+", scrubbed)
    return len(tokens) < 25


def _collect_duplicate_key_findings(value: Any, path: str, findings: list[Finding]) -> None:
    if isinstance(value, DuplicateTrackingDict):
        for key in value.duplicate_keys:
            findings.append(
                _finding(
                    "error",
                    "duplicate_json_key",
                    _child_path(path, key),
                    "JSON object contains a duplicate key.",
                )
            )
        for key, child in value.items():
            _collect_duplicate_key_findings(child, _child_path(path, key), findings)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _collect_duplicate_key_findings(child, _index_path(path, index), findings)


def load_manifest(path: Path) -> tuple[Any | None, list[Finding]]:
    """Load a manifest JSON file and report clean parse/read failures."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, [
            _finding("error", "manifest_read_error", "$", "Manifest could not be read.")
        ]
    except UnicodeDecodeError:
        return None, [
            _finding("error", "manifest_encoding_error", "$", "Manifest is not valid UTF-8.")
        ]

    try:
        manifest = json.loads(text, object_pairs_hook=DuplicateTrackingDict)
    except json.JSONDecodeError as exc:
        return None, [
            _finding(
                "error",
                "malformed_json",
                "$",
                f"Manifest is not valid JSON at line {exc.lineno}, column {exc.colno}.",
            )
        ]
    return manifest, []


def _validate_route_field(
    findings: list[Finding],
    value: Any,
    path: str,
    code: str,
) -> None:
    if isinstance(value, str) and _has_prohibited_route(value):
        findings.append(
            _finding(
                "error",
                code,
                path,
                "Route field contains a prohibited route name.",
            )
        )


def _validate_unknown_keys(
    findings: list[Finding],
    obj: dict[str, Any],
    allowed: set[str],
    path: str,
    code: str,
) -> None:
    for key in obj:
        if key not in allowed:
            findings.append(
                _finding(
                    "warning",
                    code,
                    _child_path(path, key),
                    "Unrecognized field will be ignored by this validator.",
                )
            )


def _validate_top_level(manifest: dict[str, Any], findings: list[Finding]) -> int:
    _validate_unknown_keys(
        findings, manifest, TOP_LEVEL_KEYS, "$", "unknown_top_level_field"
    )

    if "schema_version" not in manifest:
        findings.append(
            _finding("error", "missing_schema_version", "$.schema_version", "Required field is missing.")
        )
    elif manifest["schema_version"] != 3 or isinstance(manifest["schema_version"], bool):
        findings.append(
            _finding("error", "invalid_schema_version", "$.schema_version", "Schema version must equal 3.")
        )

    if "run_name" not in manifest:
        findings.append(
            _finding("error", "missing_run_name", "$.run_name", "Required field is missing.")
        )
    elif not _is_safe_slug(manifest["run_name"]):
        findings.append(
            _finding("error", "invalid_run_name", "$.run_name", "Run name must be a nonempty safe slug.")
        )

    if "workdir" not in manifest:
        findings.append(
            _finding("error", "missing_workdir", "$.workdir", "Required field is missing.")
        )
    elif not _is_nonempty_string(manifest["workdir"]):
        findings.append(
            _finding("error", "invalid_workdir", "$.workdir", "Work directory must be a nonempty string.")
        )

    if "max_parallel" not in manifest:
        findings.append(
            _finding("error", "missing_max_parallel", "$.max_parallel", "Required field is missing.")
        )
    elif not _is_int(manifest["max_parallel"]) or not 1 <= manifest["max_parallel"] <= 16:
        findings.append(
            _finding(
                "error",
                "invalid_max_parallel",
                "$.max_parallel",
                "Max parallel must be an integer from 1 through 16.",
            )
        )

    if "worktrees" not in manifest:
        findings.append(
            _finding("error", "missing_worktrees", "$.worktrees", "Required field is missing.")
        )
    elif not isinstance(manifest["worktrees"], bool):
        findings.append(
            _finding("error", "invalid_worktrees", "$.worktrees", "Worktrees must be boolean.")
        )

    if "default_engine" not in manifest:
        findings.append(
            _finding("error", "missing_default_engine", "$.default_engine", "Required field is missing.")
        )
    elif not _is_nonempty_string(manifest["default_engine"]):
        findings.append(
            _finding(
                "error",
                "invalid_default_engine",
                "$.default_engine",
                "Default engine must be a nonempty string.",
            )
        )
    else:
        _validate_route_field(
            findings,
            manifest["default_engine"],
            "$.default_engine",
            "prohibited_default_engine_route",
        )

    tasks = manifest.get("tasks")
    if "tasks" not in manifest:
        findings.append(
            _finding("error", "missing_tasks", "$.tasks", "Required field is missing.")
        )
        return 0
    if not isinstance(tasks, list):
        findings.append(
            _finding("error", "invalid_tasks", "$.tasks", "Tasks must be a nonempty list.")
        )
        return 0
    if not tasks:
        findings.append(
            _finding("error", "empty_tasks", "$.tasks", "Tasks must be a nonempty list.")
        )
    return len(tasks)


def _validate_task(
    task: Any,
    path: str,
    findings: list[Finding],
    seen_task_keys: set[str],
    seen_expected_paths: set[str],
) -> None:
    if not isinstance(task, dict):
        findings.append(
            _finding("error", "invalid_task", path, "Task entry must be a JSON object.")
        )
        return

    _validate_unknown_keys(findings, task, TASK_KEYS, path, "unknown_task_field")

    key_path = _child_path(path, "key")
    key = task.get("key")
    if "key" not in task:
        findings.append(_finding("error", "missing_task_key", key_path, "Required field is missing."))
    elif not _is_safe_slug(key):
        findings.append(
            _finding("error", "invalid_task_key", key_path, "Task key must be a nonempty safe slug.")
        )
    elif key in seen_task_keys:
        findings.append(
            _finding("error", "duplicate_task_key", key_path, "Task key must be unique.")
        )
    else:
        seen_task_keys.add(key)

    task_type_path = _child_path(path, "task_type")
    if "task_type" not in task:
        findings.append(_finding("error", "missing_task_type", task_type_path, "Required field is missing."))
    elif not _is_nonempty_string(task["task_type"]):
        findings.append(
            _finding("error", "invalid_task_type", task_type_path, "Task type must be a nonempty string.")
        )

    engine_path = _child_path(path, "engine")
    if "engine" not in task:
        findings.append(_finding("error", "missing_task_engine", engine_path, "Required field is missing."))
    elif not _is_nonempty_string(task["engine"]):
        findings.append(
            _finding("error", "invalid_task_engine", engine_path, "Engine must be a nonempty string.")
        )
    else:
        _validate_route_field(findings, task["engine"], engine_path, "prohibited_task_engine_route")

    for field in ("model", "provider"):
        if field in task:
            _validate_route_field(
                findings,
                task[field],
                _child_path(path, field),
                f"prohibited_task_{field}_route",
            )

    spec_path = _child_path(path, "spec")
    spec = task.get("spec")
    if "spec" not in task:
        findings.append(_finding("error", "missing_task_spec", spec_path, "Required field is missing."))
    elif not isinstance(spec, str):
        findings.append(_finding("error", "invalid_task_spec", spec_path, "Spec must be a string."))
    else:
        if len(spec.strip()) < 200:
            findings.append(
                _finding(
                    "error",
                    "short_task_spec",
                    spec_path,
                    "Spec must be self-contained and at least 200 characters.",
                )
            )
        if _is_pointer_only_spec(spec):
            findings.append(
                _finding(
                    "error",
                    "pointer_only_task_spec",
                    spec_path,
                    "Spec must be self-contained rather than only pointing to another file.",
                )
            )

    timeout_path = _child_path(path, "timeout_s")
    if "timeout_s" not in task:
        findings.append(_finding("error", "missing_task_timeout_s", timeout_path, "Required field is missing."))
    elif not _is_int(task["timeout_s"]) or not 60 <= task["timeout_s"] <= 1800:
        findings.append(
            _finding(
                "error",
                "invalid_task_timeout_s",
                timeout_path,
                "Timeout must be an integer from 60 through 1800 seconds.",
            )
        )

    check_path = _child_path(path, "check")
    check = task.get("check")
    if "check" not in task:
        findings.append(_finding("error", "missing_task_check", check_path, "Required field is missing."))
    elif not _is_nonempty_string(check):
        findings.append(_finding("error", "invalid_task_check", check_path, "Check must be a nonempty string."))
    else:
        if not _has_fail_fast(check):
            findings.append(
                _finding(
                    "error",
                    "check_missing_fail_fast",
                    check_path,
                    "Check must include explicit fail-fast behavior.",
                )
            )
        if not _has_pass_marker(check):
            findings.append(
                _finding(
                    "error",
                    "check_missing_pass_marker",
                    check_path,
                    "Check must include an observable PASS marker.",
                )
            )

    expect_path = _child_path(path, "expect_files")
    expect_files = task.get("expect_files")
    if "expect_files" not in task:
        findings.append(_finding("error", "missing_expect_files", expect_path, "Required field is missing."))
    elif not isinstance(expect_files, list) or not expect_files:
        findings.append(
            _finding("error", "invalid_expect_files", expect_path, "Expect files must be a nonempty list.")
        )
    else:
        for index, expected in enumerate(expect_files):
            item_path = _index_path(expect_path, index)
            if not _is_safe_relative_path(expected):
                findings.append(
                    _finding(
                        "error",
                        "unsafe_expect_file_path",
                        item_path,
                        "Expected file path must be safe and relative.",
                    )
                )
                continue
            if expected in seen_expected_paths:
                findings.append(
                    _finding(
                        "error",
                        "duplicate_expect_file_path",
                        item_path,
                        "Expected file path must not appear more than once.",
                    )
                )
            else:
                seen_expected_paths.add(expected)

    verified_path = _child_path(path, "verified")
    verified = task.get("verified")
    if "verified" not in task:
        findings.append(_finding("error", "missing_verified", verified_path, "Required field is missing."))
    elif not isinstance(verified, str):
        findings.append(
            _finding("error", "invalid_verified", verified_path, "Verified sentence must be a string.")
        )
    else:
        stripped = verified.strip()
        if len(stripped) < 40:
            findings.append(
                _finding(
                    "error",
                    "short_verified",
                    verified_path,
                    "Verified sentence must be at least 40 characters.",
                )
            )
        if not stripped.endswith("."):
            findings.append(
                _finding(
                    "error",
                    "verified_missing_period",
                    verified_path,
                    "Verified sentence must end with a period.",
                )
            )


def validate_manifest(manifest: Any, *, strict: bool = False) -> dict[str, Any]:
    """Validate a loaded manifest and return deterministic JSON-ready output."""
    findings: list[Finding] = []
    _collect_duplicate_key_findings(manifest, "$", findings)

    task_count = 0
    if not isinstance(manifest, dict):
        findings.append(
            _finding("error", "manifest_not_object", "$", "Manifest top level must be a JSON object.")
        )
    else:
        task_count = _validate_top_level(manifest, findings)
        tasks = manifest.get("tasks")
        if isinstance(tasks, list):
            seen_task_keys: set[str] = set()
            seen_expected_paths: set[str] = set()
            for index, task in enumerate(tasks):
                _validate_task(
                    task,
                    _index_path("$.tasks", index),
                    findings,
                    seen_task_keys,
                    seen_expected_paths,
                )

    errors = [finding for finding in findings if finding.severity == "error"]
    warnings = [finding for finding in findings if finding.severity == "warning"]
    valid = not errors and not (strict and warnings)
    return {
        "valid": valid,
        "errors": [finding.as_dict() for finding in errors],
        "warnings": [finding.as_dict() for finding in warnings],
        "task_count": task_count,
        "findings": [finding.as_dict() for finding in findings],
    }


def check_manifest_path(path: Path, *, strict: bool = False) -> dict[str, Any]:
    """Load and validate a manifest path."""
    manifest, load_findings = load_manifest(path)
    if load_findings:
        findings = load_findings
        return {
            "valid": False,
            "errors": [finding.as_dict() for finding in findings],
            "warnings": [],
            "task_count": 0,
            "findings": [finding.as_dict() for finding in findings],
        }
    return validate_manifest(manifest, strict=strict)


def render_report(report: dict[str, Any]) -> str:
    """Render a report as deterministic JSON."""
    return json.dumps(report, indent=2, ensure_ascii=True) + "\n"


def write_json_report(report: dict[str, Any], output_path: Path) -> None:
    """Write a JSON report atomically to the requested path."""
    target = output_path
    parent = target.parent if str(target.parent) else Path(".")
    data = render_report(report)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            temp_file.write(data)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Validate a Ringer manifest JSON file without importing Ringer."
    )
    parser.add_argument("manifest", metavar="MANIFEST", help="Path to manifest JSON.")
    parser.add_argument("--output", metavar="PATH", help="Write JSON report to PATH.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as invalid status.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    report = check_manifest_path(Path(args.manifest), strict=args.strict)

    try:
        if args.output:
            write_json_report(report, Path(args.output))
        else:
            sys.stdout.write(render_report(report))
    except OSError as exc:
        sys.stderr.write(f"Could not write output: {exc.strerror or exc.__class__.__name__}\n")
        return 2

    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
