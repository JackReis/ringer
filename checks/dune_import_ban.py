#!/usr/bin/env python3
"""FAIL-closed Dune import-graph for Ringer.

Four edges from Dune di Jaggo §3, adapted to this repo's planes:

  unprivileged_to_privileged  UI and worker Python must not import the orchestrator
  shortcut_ipc_skip           UI IPC must be a literal command on the Tauri handler
  secret_readers_in_ui        UI and worker Python must not read host secrets
  parallel_board_clients      one Ringside board; no second client or constructor

Missing policy, an undeclared edge, an unreadable scanned file, or a stale
waiver exits non-zero. A waiver is an explicit stamp in
checks/dune_import_exceptions.toml, not a silent allow.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


REQUIRED_EDGES = (
    "unprivileged_to_privileged",
    "shortcut_ipc_skip",
    "secret_readers_in_ui",
    "parallel_board_clients",
)
REQUIRED_PLANES = (
    "privileged_host",
    "unprivileged_ui",
    "unprivileged_python",
    "verification",
    "native_shell",
)
POLICY_NAME = "checks/dune_import_policy.toml"
EXCEPTIONS_NAME = "checks/dune_import_exceptions.toml"
CHECKER_NAME = "checks/dune_import_ban.py"
EXCEPTIONS_SCHEMA = "ringer.dune-import-exceptions/v1"
POLICY_SCHEMA = "ringer.dune-import-ban/v1"
STAMP_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._:-]{7,128}$")
JS_SPEC_RE = re.compile(
    r"""(?:\bfrom\s+|require\(\s*)['\"](?P<spec>[^'\"]+)['\"]"""
)
STRING_IMPORT_RE = re.compile(
    r"""(?:__import__|import_module)\(\s*['\"]ringer(?:\.|['\"])|['\"]import ringer['\"]|['\"]from ringer\b"""
)
HANDLER_RE = re.compile(r"generate_handler!\s*\[(?P<body>.*?)\]", re.DOTALL)
IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
INVOKE_RE = re.compile(r"\b(?P<fn>tauriInvoke|TAURI_INVOKE)\(\s*(?P<arg>[^)\n]*)")
DOT_INVOKE_RE = re.compile(r"""\.invoke\(\s*(['"])(?P<cmd>[^'"]+)\1""")
LOOPBACK_RE = re.compile(
    r"https?://(?:127\.0\.0\.1|localhost)(?::(?P<port>\d+|\$\{[^}]+\}))?"
)


@dataclass(frozen=True)
class Finding:
    edge: str
    path: str
    line: int
    detail: str
    line_text: str = ""

    def format(self) -> str:
        quote = f" ({self.line_text.strip()})" if self.line_text.strip() else ""
        return f"FAIL {self.edge} {self.path}:{self.line}: {self.detail}{quote}"


@dataclass(frozen=True)
class ExceptionWaiver:
    edge: str
    path: str
    pattern: str
    stamp: str
    reason: str
    line: int


@dataclass
class ScanResult:
    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0
    edges: tuple[str, ...] = REQUIRED_EDGES


def scan_root(
    root: Path,
    *,
    policy_path: Path | None = None,
    exceptions_path: Path | None = None,
) -> ScanResult:
    root = root.resolve()
    policy_file = (policy_path or (root / POLICY_NAME)).resolve()
    exceptions_file = (exceptions_path or (root / EXCEPTIONS_NAME)).resolve()
    findings: list[Finding] = []
    scanned: set[str] = set()

    policy, policy_findings = _load_policy(root, policy_file)
    findings.extend(policy_findings)
    waivers, waiver_findings = _load_exceptions(root, exceptions_file)
    findings.extend(waiver_findings)
    if policy is None:
        return ScanResult(findings=_unique(findings), files_scanned=len(scanned))

    plane_files = _plane_files(root, policy, findings, scanned)
    if any(item.edge == "unprivileged_to_privileged" and item.path == _rel(root, policy_file) for item in findings):
        # Plane discovery already recorded structural failures. Keep scanning
        # whatever did resolve so one bad glob does not hide a real edge.
        pass

    _edge_unprivileged_imports(root, policy, plane_files, findings, scanned)
    _edge_shortcut_ipc(root, policy, plane_files, findings, scanned)
    _edge_secret_readers(root, policy, plane_files, findings, scanned)
    _edge_parallel_boards(root, policy, plane_files, findings, scanned)

    code_findings = [item for item in findings if _waiver_applies_to(item)]
    structural = [item for item in findings if not _waiver_applies_to(item)]
    kept, used = _apply_waivers(code_findings, waivers)
    for waiver in waivers:
        if id(waiver) not in used:
            kept.append(
                Finding(
                    edge=waiver.edge,
                    path=EXCEPTIONS_NAME,
                    line=waiver.line,
                    detail=(
                        f"stale stamp {waiver.stamp} matches no {waiver.edge} "
                        f"finding at {waiver.path}"
                    ),
                )
            )
    return ScanResult(
        findings=_unique(structural + kept),
        files_scanned=len(scanned),
    )


def _waiver_applies_to(finding: Finding) -> bool:
    if finding.path in {POLICY_NAME, EXCEPTIONS_NAME}:
        return False
    if finding.detail.startswith("FAIL-closed:"):
        return False
    return True


def _load_policy(root: Path, path: Path) -> tuple[dict | None, list[Finding]]:
    rel = _rel(root, path) if path.is_file() else POLICY_NAME
    if not path.is_file():
        return None, [
            Finding(
                edge="unprivileged_to_privileged",
                path=POLICY_NAME,
                line=1,
                detail="FAIL-closed: import policy is missing",
            )
        ]
    try:
        text = path.read_text(encoding="utf-8")
        policy = tomllib.loads(text)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        return None, [
            Finding(
                edge="unprivileged_to_privileged",
                path=rel,
                line=1,
                detail=f"FAIL-closed: could not read import policy ({exc.__class__.__name__})",
            )
        ]
    findings: list[Finding] = []
    if policy.get("schema") != POLICY_SCHEMA:
        findings.append(
            Finding(
                edge="unprivileged_to_privileged",
                path=rel,
                line=1,
                detail=f"FAIL-closed: policy schema must be {POLICY_SCHEMA}",
            )
        )
    planes = policy.get("planes")
    edges = policy.get("edges")
    if not isinstance(planes, dict) or not isinstance(edges, dict):
        findings.append(
            Finding(
                edge="unprivileged_to_privileged",
                path=rel,
                line=1,
                detail="FAIL-closed: policy needs [planes] and [edges] tables",
            )
        )
        return None, findings
    for name in REQUIRED_PLANES:
        if name not in planes or not isinstance(planes[name], dict):
            findings.append(
                Finding(
                    edge="unprivileged_to_privileged",
                    path=rel,
                    line=1,
                    detail=f"FAIL-closed: plane {name} is not declared",
                )
            )
    declared = tuple(edges)
    missing = [name for name in REQUIRED_EDGES if name not in edges]
    unknown = [name for name in declared if name not in REQUIRED_EDGES]
    for name in REQUIRED_EDGES:
        if name in edges and not isinstance(edges[name], dict):
            findings.append(
                Finding(
                    edge=name,
                    path=rel,
                    line=1,
                    detail="FAIL-closed: edge table is not a table",
                )
            )
    for name in missing:
        findings.append(
            Finding(
                edge=name,
                path=rel,
                line=1,
                detail="FAIL-closed: policy does not declare this edge",
            )
        )
    for name in unknown:
        findings.append(
            Finding(
                edge="unprivileged_to_privileged",
                path=rel,
                line=1,
                detail=f"FAIL-closed: unknown edge {name}",
            )
        )
    if missing or unknown or findings:
        # Still return the policy so file-level edges run when the tables exist.
        if missing or unknown:
            return policy, findings
    return policy, findings


def _load_exceptions(root: Path, path: Path) -> tuple[list[ExceptionWaiver], list[Finding]]:
    rel = _rel(root, path) if path.is_file() else EXCEPTIONS_NAME
    if not path.is_file():
        return [], [
            Finding(
                edge="unprivileged_to_privileged",
                path=EXCEPTIONS_NAME,
                line=1,
                detail="FAIL-closed: exceptions file is missing; zero waivers must be explicit",
            )
        ]
    try:
        text = path.read_text(encoding="utf-8")
        parsed = tomllib.loads(text)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        return [], [
            Finding(
                edge="unprivileged_to_privileged",
                path=rel,
                line=1,
                detail=f"FAIL-closed: could not read exceptions ({exc.__class__.__name__})",
            )
        ]
    findings: list[Finding] = []
    if parsed.get("schema") != EXCEPTIONS_SCHEMA:
        findings.append(
            Finding(
                edge="unprivileged_to_privileged",
                path=rel,
                line=1,
                detail=f"FAIL-closed: exceptions schema must be {EXCEPTIONS_SCHEMA}",
            )
        )
    raw = parsed.get("exceptions", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        findings.append(
            Finding(
                edge="unprivileged_to_privileged",
                path=rel,
                line=1,
                detail="FAIL-closed: exceptions must be an array of tables",
            )
        )
        return [], findings
    waivers: list[ExceptionWaiver] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            findings.append(
                Finding(
                    edge="unprivileged_to_privileged",
                    path=rel,
                    line=index,
                    detail="FAIL-closed: exception entry is not a table",
                )
            )
            continue
        edge = str(item.get("edge") or "")
        waiver_path = str(item.get("path") or "")
        pattern = str(item.get("pattern") or "")
        stamp = str(item.get("stamp") or "")
        reason = str(item.get("reason") or "")
        problems: list[str] = []
        if edge not in REQUIRED_EDGES:
            problems.append("edge")
        if not waiver_path or waiver_path.endswith("/") or ".." in Path(waiver_path).parts:
            problems.append("path")
        if waiver_path in {POLICY_NAME, EXCEPTIONS_NAME}:
            problems.append("path-is-policy")
        if len(pattern) < 8:
            problems.append("pattern")
        if not STAMP_RE.fullmatch(stamp):
            problems.append("stamp")
        if len(reason.strip()) < 12:
            problems.append("reason")
        if problems:
            findings.append(
                Finding(
                    edge=edge or "unprivileged_to_privileged",
                    path=rel,
                    line=index,
                    detail="FAIL-closed: exception missing " + ", ".join(problems),
                )
            )
            continue
        waivers.append(
            ExceptionWaiver(
                edge=edge,
                path=waiver_path.replace("\\", "/"),
                pattern=pattern,
                stamp=stamp,
                reason=reason.strip(),
                line=index,
            )
        )
    return waivers, findings


def _plane_files(
    root: Path,
    policy: dict,
    findings: list[Finding],
    scanned: set[str],
) -> dict[str, list[Path]]:
    planes = policy.get("planes") or {}
    resolved: dict[str, list[Path]] = {}
    for name in REQUIRED_PLANES:
        spec = planes.get(name)
        globs = spec.get("globs") if isinstance(spec, dict) else None
        if not isinstance(globs, list) or not globs:
            findings.append(
                Finding(
                    edge="unprivileged_to_privileged",
                    path=POLICY_NAME,
                    line=1,
                    detail=f"FAIL-closed: plane {name} has no globs",
                )
            )
            resolved[name] = []
            continue
        files: list[Path] = []
        for pattern in globs:
            if not isinstance(pattern, str) or not pattern:
                findings.append(
                    Finding(
                        edge="unprivileged_to_privileged",
                        path=POLICY_NAME,
                        line=1,
                        detail=f"FAIL-closed: plane {name} has an empty glob",
                    )
                )
                continue
            files.extend(_glob(root, pattern, findings, scanned))
        unique = _unique_paths(files)
        if not unique:
            findings.append(
                Finding(
                    edge="unprivileged_to_privileged",
                    path=POLICY_NAME,
                    line=1,
                    detail=f"FAIL-closed: plane {name} matched no files",
                )
            )
        resolved[name] = unique
    return resolved


def _edge_unprivileged_imports(
    root: Path,
    policy: dict,
    plane_files: dict[str, list[Path]],
    findings: list[Finding],
    scanned: set[str],
) -> None:
    edge = policy["edges"].get("unprivileged_to_privileged")
    if not isinstance(edge, dict):
        return
    banned_modules = _require_nonempty(
        edge.get("banned_modules"),
        "unprivileged_to_privileged",
        "banned_modules is empty",
        findings,
    )
    banned_specifiers = _str_list(edge.get("banned_specifiers"))
    from_planes = _require_nonempty(
        edge.get("from_planes"),
        "unprivileged_to_privileged",
        "unprivileged_to_privileged.from_planes is empty",
        findings,
    )
    if not banned_modules or not from_planes:
        return
    for plane in from_planes:
        for path in plane_files.get(plane, []):
            rel = _track(root, path, scanned)
            text = _read(path, "unprivileged_to_privileged", rel, findings)
            if text is None:
                continue
            if path.suffix == ".py":
                _python_imports(text, rel, banned_modules, findings)
            _specifier_imports(text, rel, banned_modules, banned_specifiers, findings)
            for match in STRING_IMPORT_RE.finditer(text):
                line_no, line_text = _line_at(text, match.start())
                findings.append(
                    Finding(
                        edge="unprivileged_to_privileged",
                        path=rel,
                        line=line_no,
                        detail="unprivileged plane imports privileged module 'ringer'",
                        line_text=line_text,
                    )
                )


def _python_imports(text: str, rel: str, banned_modules: list[str], findings: list[Finding]) -> None:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        findings.append(
            Finding(
                edge="unprivileged_to_privileged",
                path=rel,
                line=exc.lineno or 1,
                detail="FAIL-closed: could not parse Python imports",
                line_text=(exc.text or "").rstrip("\n"),
            )
        )
        return
    banned = set(banned_modules)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_name = alias.name.split(".", 1)[0]
                if root_name in banned:
                    findings.append(
                        Finding(
                            edge="unprivileged_to_privileged",
                            path=rel,
                            line=node.lineno,
                            detail=f"unprivileged plane imports privileged module '{root_name}'",
                            line_text=_source_segment(text, node.lineno),
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root_name = module.split(".", 1)[0] if module else ""
            names = [alias.name for alias in node.names]
            if root_name in banned or any(name in banned for name in names):
                chosen = root_name if root_name in banned else next(name for name in names if name in banned)
                findings.append(
                    Finding(
                        edge="unprivileged_to_privileged",
                        path=rel,
                        line=node.lineno,
                        detail=f"unprivileged plane imports privileged module '{chosen}'",
                        line_text=_source_segment(text, node.lineno),
                    )
                )
        elif isinstance(node, ast.Call):
            target = _call_name(node.func)
            if target not in {"import_module", "__import__"}:
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            if not isinstance(node.args[0].value, str):
                continue
            root_name = node.args[0].value.split(".", 1)[0]
            if root_name in banned:
                findings.append(
                    Finding(
                        edge="unprivileged_to_privileged",
                        path=rel,
                        line=node.lineno,
                        detail=f"unprivileged plane imports privileged module '{root_name}'",
                        line_text=_source_segment(text, node.lineno),
                    )
                )


def _specifier_imports(
    text: str,
    rel: str,
    banned_modules: list[str],
    banned_specifiers: list[str],
    findings: list[Finding],
) -> None:
    for match in JS_SPEC_RE.finditer(text):
        spec = match.group("spec").replace("\\", "/")
        if not _specifier_banned(spec, banned_modules, banned_specifiers):
            continue
        line_no, line_text = _line_at(text, match.start())
        findings.append(
            Finding(
                edge="unprivileged_to_privileged",
                path=rel,
                line=line_no,
                detail=f"unprivileged plane imports privileged specifier '{spec}'",
                line_text=line_text,
            )
        )


def _edge_shortcut_ipc(
    root: Path,
    policy: dict,
    plane_files: dict[str, list[Path]],
    findings: list[Finding],
    scanned: set[str],
) -> None:
    edge = policy["edges"].get("shortcut_ipc_skip")
    if not isinstance(edge, dict):
        return
    commands = _handler_commands(root, edge, findings, scanned)
    _capability_permissions(root, edge, findings, scanned)
    _asset_scope(root, edge, findings, scanned)
    banned = _require_nonempty(
        edge.get("banned_substrings"),
        "shortcut_ipc_skip",
        "shortcut IPC banned_substrings is empty",
        findings,
    )
    ui_planes = _require_nonempty(
        edge.get("ui_planes"),
        "shortcut_ipc_skip",
        "shortcut_ipc_skip.ui_planes is empty",
        findings,
    )
    forward = str(edge.get("sanctioned_forward") or "")
    if not forward:
        findings.append(
            Finding(
                edge="shortcut_ipc_skip",
                path=POLICY_NAME,
                line=1,
                detail="FAIL-closed: sanctioned_forward is empty",
            )
        )
    forward_compact = _compact(forward)
    for plane in ui_planes:
        for path in plane_files.get(plane, []):
            rel = _track(root, path, scanned)
            text = _read(path, "shortcut_ipc_skip", rel, findings)
            if text is None:
                continue
            _banned_lines(text, rel, "shortcut_ipc_skip", banned, "shortcut IPC", findings)
            _invoke_calls(text, rel, commands, forward_compact, findings)


def _handler_commands(
    root: Path,
    edge: dict,
    findings: list[Finding],
    scanned: set[str],
) -> set[str]:
    pattern = str(edge.get("rust_glob") or "")
    if not pattern:
        findings.append(
            Finding(
                edge="shortcut_ipc_skip",
                path=POLICY_NAME,
                line=1,
                detail="FAIL-closed: rust_glob is empty",
            )
        )
        return set()
    files = _glob(root, pattern, findings, scanned)
    commands: set[str] = set()
    if not files:
        findings.append(
            Finding(
                edge="shortcut_ipc_skip",
                path=POLICY_NAME,
                line=1,
                detail="FAIL-closed: Tauri generate_handler surface matched no files",
            )
        )
        return commands
    for path in files:
        rel = _track(root, path, scanned)
        text = _read(path, "shortcut_ipc_skip", rel, findings)
        if text is None:
            continue
        for match in HANDLER_RE.finditer(text):
            commands.update(IDENT_RE.findall(match.group("body")))
    if not commands:
        findings.append(
            Finding(
                edge="shortcut_ipc_skip",
                path=POLICY_NAME,
                line=1,
                detail="FAIL-closed: generate_handler! listed no commands",
            )
        )
    return commands


def _capability_permissions(
    root: Path,
    edge: dict,
    findings: list[Finding],
    scanned: set[str],
) -> None:
    pattern = str(edge.get("capabilities_glob") or "")
    prefixes = _str_list(edge.get("allowed_permission_prefixes"))
    if not pattern or not prefixes:
        findings.append(
            Finding(
                edge="shortcut_ipc_skip",
                path=POLICY_NAME,
                line=1,
                detail="FAIL-closed: capability allowlist is incomplete",
            )
        )
        return
    files = _glob(root, pattern, findings, scanned)
    if not files:
        findings.append(
            Finding(
                edge="shortcut_ipc_skip",
                path=POLICY_NAME,
                line=1,
                detail="FAIL-closed: capability files matched nothing",
            )
        )
        return
    for path in files:
        rel = _track(root, path, scanned)
        text = _read(path, "shortcut_ipc_skip", rel, findings)
        if text is None:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            findings.append(
                Finding(
                    edge="shortcut_ipc_skip",
                    path=rel,
                    line=1,
                    detail=f"FAIL-closed: capability JSON did not parse ({exc.msg})",
                )
            )
            continue
        permissions = payload.get("permissions") if isinstance(payload, dict) else None
        if not isinstance(permissions, list) or not permissions:
            findings.append(
                Finding(
                    edge="shortcut_ipc_skip",
                    path=rel,
                    line=1,
                    detail="FAIL-closed: capability permissions are missing",
                )
            )
            continue
        for permission in permissions:
            rendered = str(permission)
            if _permission_allowed(rendered, prefixes):
                continue
            findings.append(
                Finding(
                    edge="shortcut_ipc_skip",
                    path=rel,
                    line=1,
                    detail=f"capability grants {rendered}, outside the window IPC allowlist",
                    line_text=rendered,
                )
            )


def _asset_scope(
    root: Path,
    edge: dict,
    findings: list[Finding],
    scanned: set[str],
) -> None:
    rel_conf = str(edge.get("tauri_conf") or "")
    must_contain = str(edge.get("asset_scope_must_contain") or "")
    banned = _str_list(edge.get("asset_scope_banned_substrings"))
    if not rel_conf or not must_contain or not banned:
        findings.append(
            Finding(
                edge="shortcut_ipc_skip",
                path=POLICY_NAME,
                line=1,
                detail="FAIL-closed: asset protocol scope rule is incomplete",
            )
        )
        return
    path = root / rel_conf
    if not path.is_file():
        findings.append(
            Finding(
                edge="shortcut_ipc_skip",
                path=rel_conf,
                line=1,
                detail="FAIL-closed: tauri.conf.json is missing",
            )
        )
        return
    rel = _track(root, path, scanned)
    text = _read(path, "shortcut_ipc_skip", rel, findings)
    if text is None:
        return
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        findings.append(
            Finding(
                edge="shortcut_ipc_skip",
                path=rel,
                line=1,
                detail=f"FAIL-closed: tauri.conf.json did not parse ({exc.msg})",
            )
        )
        return
    security = ((payload.get("app") or {}).get("security") or {}) if isinstance(payload, dict) else {}
    protocol = security.get("assetProtocol") if isinstance(security, dict) else None
    if not isinstance(protocol, dict) or protocol.get("enable") is not True:
        findings.append(
            Finding(
                edge="shortcut_ipc_skip",
                path=rel,
                line=1,
                detail="FAIL-closed: asset protocol must stay explicitly enabled and scoped",
            )
        )
        return
    scope = protocol.get("scope")
    if not isinstance(scope, list) or not scope:
        findings.append(
            Finding(
                edge="shortcut_ipc_skip",
                path=rel,
                line=1,
                detail="FAIL-closed: asset protocol scope is empty",
            )
        )
        return
    for entry in scope:
        rendered = str(entry)
        if must_contain not in rendered or any(piece in rendered for piece in banned):
            findings.append(
                Finding(
                    edge="shortcut_ipc_skip",
                    path=rel,
                    line=1,
                    detail=f"asset protocol scope is not limited to artifact files: {rendered}",
                    line_text=rendered,
                )
            )


def _invoke_calls(
    text: str,
    rel: str,
    commands: set[str],
    forward_compact: str,
    findings: list[Finding],
) -> None:
    for match in INVOKE_RE.finditer(text):
        line_no, line_text = _line_at(text, match.start())
        fn = match.group("fn")
        arg = match.group("arg").strip()
        if fn == "tauriInvoke" and re.search(r"\bfunction\s+$", text[max(0, match.start() - 16) : match.start()]):
            continue
        literal = re.match(r"""(?P<q>['\"])(?P<cmd>[^'\"]+)(?P=q)""", arg)
        if literal:
            command = literal.group("cmd")
            if command not in commands:
                findings.append(
                    Finding(
                        edge="shortcut_ipc_skip",
                        path=rel,
                        line=line_no,
                        detail=f"IPC command '{command}' is not on generate_handler!",
                        line_text=line_text,
                    )
                )
            continue
        if fn == "TAURI_INVOKE" and forward_compact and forward_compact in _compact(line_text):
            continue
        findings.append(
            Finding(
                edge="shortcut_ipc_skip",
                path=rel,
                line=line_no,
                detail="IPC call skips the literal tauriInvoke allowlist",
                line_text=line_text,
            )
        )
    for match in DOT_INVOKE_RE.finditer(text):
        line_no, line_text = _line_at(text, match.start())
        findings.append(
            Finding(
                edge="shortcut_ipc_skip",
                path=rel,
                line=line_no,
                detail=f"direct .invoke('{match.group('cmd')}') skips tauriInvoke",
                line_text=line_text,
            )
        )


def _edge_secret_readers(
    root: Path,
    policy: dict,
    plane_files: dict[str, list[Path]],
    findings: list[Finding],
    scanned: set[str],
) -> None:
    edge = policy["edges"].get("secret_readers_in_ui")
    if not isinstance(edge, dict):
        return
    banned = _require_nonempty(
        edge.get("banned_substrings"),
        "secret_readers_in_ui",
        "secret-reader patterns are empty",
        findings,
    )
    planes = _require_nonempty(
        edge.get("planes"),
        "secret_readers_in_ui",
        "secret_readers_in_ui.planes is empty",
        findings,
    )
    if not banned or not planes:
        return
    for plane in planes:
        for path in plane_files.get(plane, []):
            rel = _track(root, path, scanned)
            text = _read(path, "secret_readers_in_ui", rel, findings)
            if text is None:
                continue
            _banned_lines(text, rel, "secret_readers_in_ui", banned, "secret reader", findings)


def _edge_parallel_boards(
    root: Path,
    policy: dict,
    plane_files: dict[str, list[Path]],
    findings: list[Finding],
    scanned: set[str],
) -> None:
    edge = policy["edges"].get("parallel_board_clients")
    if not isinstance(edge, dict):
        return
    ui_banned = _str_list(edge.get("ui_banned_substrings"))
    shell_banned = _str_list(edge.get("native_shell_banned_substrings"))
    symbols = _str_list(edge.get("board_symbols"))
    ui_planes = _str_list(edge.get("ui_planes"))
    owner = str(edge.get("board_owner") or "")
    if not ui_banned or not shell_banned or not symbols or not owner or not ui_planes:
        findings.append(
            Finding(
                edge="parallel_board_clients",
                path=POLICY_NAME,
                line=1,
                detail="FAIL-closed: parallel-board rule is incomplete",
            )
        )
        return
    for plane in ui_planes:
        for path in plane_files.get(plane, []):
            rel = _track(root, path, scanned)
            text = _read(path, "parallel_board_clients", rel, findings)
            if text is None:
                continue
            _banned_lines(text, rel, "parallel_board_clients", ui_banned, "parallel board client", findings)
            _loopback_ports(text, rel, findings)
    shell_plane = str(edge.get("native_shell_plane") or "")
    for path in plane_files.get(shell_plane, []):
        rel = _track(root, path, scanned)
        text = _read(path, "parallel_board_clients", rel, findings)
        if text is None:
            continue
        _banned_lines(
            text,
            rel,
            "parallel_board_clients",
            shell_banned,
            "native shell opened a second board client",
            findings,
        )
    allowed_prefixes = [owner]
    for path in plane_files.get("verification", []):
        allowed_prefixes.append(_track(root, path, scanned))
    allowed_prefixes.append(CHECKER_NAME)
    for path in sorted(root.rglob("*.py")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rel = _rel(root, path)
        if rel is None:
            findings.append(
                Finding(
                    edge="parallel_board_clients",
                    path=str(path),
                    line=1,
                    detail="FAIL-closed: Python path escapes the repo root",
                )
            )
            continue
        if rel == owner or rel == CHECKER_NAME or rel.startswith("tests/"):
            continue
        text = _read(path, "parallel_board_clients", rel, findings)
        if text is None:
            _track(root, path, scanned)
            continue
        _track(root, path, scanned)
        for symbol in symbols:
            _symbol_lines(text, rel, symbol, findings)


def _loopback_ports(text: str, rel: str, findings: list[Finding]) -> None:
    for match in LOOPBACK_RE.finditer(text):
        port = match.group("port")
        if port and port.startswith("${"):
            continue
        line_no, line_text = _line_at(text, match.start())
        shown = port or "80"
        findings.append(
            Finding(
                edge="parallel_board_clients",
                path=rel,
                line=line_no,
                detail=f"loopback URL pins port {shown}; the page origin is the one board client",
                line_text=line_text,
            )
        )


def _symbol_lines(text: str, rel: str, symbol: str, findings: list[Finding]) -> None:
    for index, line in enumerate(text.splitlines(), start=1):
        if re.search(rf"\b{re.escape(symbol)}\b", line):
            findings.append(
                Finding(
                    edge="parallel_board_clients",
                    path=rel,
                    line=index,
                    detail=f"board symbol {symbol} is only constructed in ringer.py",
                    line_text=line,
                )
            )


def _banned_lines(
    text: str,
    rel: str,
    edge: str,
    needles: list[str],
    label: str,
    findings: list[Finding],
) -> None:
    if not needles:
        return
    for index, line in enumerate(text.splitlines(), start=1):
        for needle in needles:
            if needle in line:
                findings.append(
                    Finding(
                        edge=edge,
                        path=rel,
                        line=index,
                        detail=f"{label} pattern {needle!r}",
                        line_text=line,
                    )
                )


def _apply_waivers(
    findings: list[Finding],
    waivers: list[ExceptionWaiver],
) -> tuple[list[Finding], set[int]]:
    used: set[int] = set()
    kept: list[Finding] = []
    for finding in findings:
        matched = False
        for waiver in waivers:
            if waiver.edge != finding.edge or waiver.path != finding.path:
                continue
            haystack = finding.line_text or finding.detail
            if waiver.pattern not in haystack:
                continue
            used.add(id(waiver))
            matched = True
            break
        if not matched:
            kept.append(finding)
    return kept, used


def _glob(root: Path, pattern: str, findings: list[Finding], scanned: set[str]) -> list[Path]:
    found: list[Path] = []
    for path in root.glob(pattern):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rel = _rel(root, path)
        if rel is None:
            findings.append(
                Finding(
                    edge="unprivileged_to_privileged",
                    path=pattern,
                    line=1,
                    detail=f"FAIL-closed: glob {pattern} escaped the repo root",
                )
            )
            continue
        found.append(path)
        scanned.add(rel)
    return found


def _read(path: Path, edge: str, rel: str, findings: list[Finding]) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        findings.append(
            Finding(
                edge=edge,
                path=rel,
                line=1,
                detail=f"FAIL-closed: could not read file ({exc.__class__.__name__})",
            )
        )
        return None


def _track(root: Path, path: Path, scanned: set[str]) -> str:
    rel = _rel(root, path) or path.as_posix()
    scanned.add(rel)
    return rel


def _rel(root: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _line_at(text: str, offset: int) -> tuple[int, str]:
    line_no = text.count("\n", 0, offset) + 1
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    if end == -1:
        end = len(text)
    return line_no, text[start:end]


def _source_segment(text: str, line_no: int) -> str:
    lines = text.splitlines()
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return ""


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _specifier_banned(spec: str, banned_modules: list[str], banned_specifiers: list[str]) -> bool:
    for banned in banned_specifiers:
        if spec == banned or spec.startswith(banned + "/"):
            return True
    tail = spec.rsplit("/", 1)[-1]
    stem = tail[:-3] if tail.endswith(".py") else tail
    return tail in banned_modules or stem in banned_modules


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _permission_allowed(rendered: str, prefixes: list[str]) -> bool:
    for prefix in prefixes:
        if prefix.endswith(":"):
            if rendered.startswith(prefix):
                return True
        elif rendered == prefix:
            return True
    return False


def _require_nonempty(value: object, edge: str, detail: str, findings: list[Finding]) -> list[str]:
    items = _str_list(value)
    if not items:
        findings.append(
            Finding(
                edge=edge,
                path=POLICY_NAME,
                line=1,
                detail=f"FAIL-closed: {detail}",
            )
        )
    return items


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _unique(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple[str, str, int, str]] = set()
    ordered: list[Finding] = []
    for finding in findings:
        key = (finding.edge, finding.path, finding.line, finding.detail)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(finding)
    return ordered


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(path)
    return ordered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FAIL-closed Dune import-graph for Ringer")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--policy", type=Path, default=None)
    parser.add_argument("--exceptions", type=Path, default=None)
    args = parser.parse_args(argv)
    result = scan_root(args.root, policy_path=args.policy, exceptions_path=args.exceptions)
    if result.findings:
        for finding in result.findings:
            print(finding.format())
        print(
            f"dune-import-ban: FAIL ({len(result.findings)} finding(s), {result.files_scanned} files)",
            file=sys.stderr,
        )
        return 1
    print(f"dune-import-ban: PASS ({result.files_scanned} files, {len(result.edges)} edges)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
