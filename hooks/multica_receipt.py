#!/usr/bin/env python3
"""Multica Judge-receipt posting for Ringer (AEGI-78 / Spec 01).

Posts one Multica comment after a Judge verdict is logged to runs.jsonl.
Designed for in-process use from ringer.py and as a CLI (supersedes the
SAFE-NOW wrapper ~/.hermes/bin/ringer-multica-receipt for new invocations;
the wrapper remains for PATH cutover lag).

Env:
  RINGER_MULTICA_RECEIPT=0   disable (default: on when an issue id is present)
  MULTICA_ISSUE_ID           owning AEGI issue (e.g. AEGI-78)
  RINGER_MULTICA_RINGSIDE_URL  override Ringside URL (default Tailscale HUD)

Idempotent on run_id via ~/.ringer/receipts/multica-posted.json
Comment only — never wakes Multica agents (no assignee / no issue update start).
Fail-open: posting errors are returned/logged; they must not flip PASS→FAIL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG = logging.getLogger("ringer.multica_receipt")

STALE_HOURS = 48
DEFAULT_RINGSIDE_URL = "https://aegis.tailc2f398.ts.net/ringside/"
POSTED_REL = Path("receipts") / "multica-posted.json"
RUNS_NAME = "runs.jsonl"


def state_dir(override: Path | None = None) -> Path:
    if override is not None:
        return Path(override)
    env = os.environ.get("RINGER_HOME") or os.environ.get("RINGER_STATE_DIR")
    if env:
        return Path(env)
    return Path.home() / ".ringer"


def posted_path(state: Path) -> Path:
    return state / POSTED_REL


def runs_path(state: Path) -> Path:
    return state / RUNS_NAME


def receipt_enabled() -> bool:
    """Feature flag: off only when explicitly 0; otherwise on if issue present."""
    return os.environ.get("RINGER_MULTICA_RECEIPT", "1") != "0"


def resolve_issue_id(explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    return (os.environ.get("MULTICA_ISSUE_ID") or "").strip()


def load_posted(state: Path) -> set[str]:
    path = posted_path(state)
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("run_ids") or [])
    except Exception:
        return set()


def save_posted(state: Path, ids: set[str]) -> None:
    path = posted_path(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_ids": sorted(ids),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    # Atomic replace avoids truncated ledger on crash mid-write (review B-1).
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def latest_run_logged_at(state: Path) -> datetime | None:
    path = runs_path(state)
    if not path.exists():
        return None
    last: datetime | None = None
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            dt = _parse_ts(row.get("logged_at"))
            if dt is not None:
                last = dt
    return last


def ringside_ref(state: Path, *, now: datetime | None = None) -> str:
    """Return Ringside URL or withheld-stale if ledger/HUD stale >48h."""
    latest = latest_run_logged_at(state)
    now = now or datetime.now(timezone.utc)
    if latest is None:
        return "withheld-stale"
    age = (now - latest.astimezone(timezone.utc)).total_seconds()
    if age > STALE_HOURS * 3600:
        return "withheld-stale"
    return os.environ.get("RINGER_MULTICA_RINGSIDE_URL") or DEFAULT_RINGSIDE_URL


def find_run(
    state: Path,
    *,
    run_id: str | None = None,
    from_last: bool = False,
) -> dict[str, Any]:
    path = runs_path(state)
    if not path.exists():
        raise FileNotFoundError(f"runs.jsonl missing: {path}")
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if from_last:
        if not rows:
            raise ValueError("runs.jsonl empty")
        return rows[-1]
    if not run_id:
        raise ValueError("need run_id or from_last")
    for row in reversed(rows):
        if row.get("run_id") == run_id:
            return row
    raise KeyError(f"run_id not found: {run_id}")


def artifact_path_for(run: dict[str, Any]) -> str:
    for key in ("artifact", "artifact_path"):
        if run.get(key):
            return str(run[key])
    notes = run.get("notes") or ""
    for token in str(notes).split():
        if token.startswith("/") or token.startswith("~"):
            return token
    rid = run.get("run_id") or "unknown"
    return f"~/.ringer/runs/{rid}.json (or runs.jsonl entry)"


def sha_hint(path_s: str, *, logged_at: str = "") -> str:
    p = Path(path_s).expanduser()
    if p.is_file():
        h = hashlib.sha256()
        with p.open("rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        digest = h.hexdigest()[:16]
        mtime = datetime.fromtimestamp(p.stat().st_mtime).astimezone().isoformat(
            timespec="seconds"
        )
        return f"sha256:{digest} mtime:{mtime}"
    return f"ledger_logged_at:{logged_at}"


def format_receipt_body(
    *,
    issue_id: str,
    run: dict[str, Any],
    ringside: str,
    lane: str = "oe-ringer",
    host: str = "Aegis",
    posted_at: datetime | None = None,
) -> str:
    rid = str(run.get("run_id") or "")
    verdict = str(run.get("verdict") or "N/A")
    logged_at = str(run.get("logged_at") or "")
    art = artifact_path_for(run)
    try:
        sha = sha_hint(art, logged_at=logged_at)
    except Exception:
        sha = f"ledger_logged_at:{logged_at}"
    when = posted_at or datetime.now().astimezone()
    # Prefer America/Chicago wall clock label when zoneinfo available.
    try:
        from zoneinfo import ZoneInfo

        when_ct = when.astimezone(ZoneInfo("America/Chicago"))
    except Exception:
        when_ct = when
    stamp = when_ct.strftime("%Y-%m-%d %H:%M %Z")
    return (
        f"RECEIPT {lane} on {host} — {issue_id}\n"
        f"- run_id: {rid}\n"
        f"- verdict: {verdict}\n"
        f"- artifact: {art}\n"
        f"- ringside: {ringside}\n"
        f"- Multica issue: {issue_id}\n"
        f"- sha/mtime: {sha}\n"
        f"- logged_at: {logged_at}\n"
        f"- posted_at: {stamp}\n"
        f"- gates: held (comment-only; no Multica agent wake; no hermes --replace)\n"
        f"- next: none\n"
    )


def post_multica_comment(
    issue_id: str,
    body: str,
    *,
    dry_run: bool = False,
    multica_bin: str = "multica",
) -> dict[str, Any]:
    """Post comment via multica CLI. Uses --content (Spec / CoS). Comment-only."""
    if dry_run:
        return {"ok": True, "dry_run": True, "body": body}
    # Prefer --content for short bodies; fall back to --content-stdin for safety
    # with newlines. Never use issue update (avoids --no-start wake path entirely).
    cmd = [
        multica_bin,
        "issue",
        "comment",
        "add",
        issue_id,
        "--content",
        body,
        "--output",
        "json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return {
            "ok": False,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    return {"ok": True, "stdout": proc.stdout, "stderr": proc.stderr}


class ReceiptResult:
    __slots__ = ("status", "run_id", "issue_id", "detail")

    def __init__(
        self,
        status: str,
        *,
        run_id: str = "",
        issue_id: str = "",
        detail: str = "",
    ) -> None:
        self.status = status  # posted | skipped | disabled | error | missing_issue
        self.run_id = run_id
        self.issue_id = issue_id
        self.detail = detail

    def __repr__(self) -> str:
        return (
            f"ReceiptResult(status={self.status!r}, run_id={self.run_id!r}, "
            f"issue_id={self.issue_id!r}, detail={self.detail!r})"
        )


def maybe_post_receipt(
    *,
    run_id: str | None = None,
    from_last: bool = False,
    issue_id: str | None = None,
    state_dir_path: Path | None = None,
    lane: str = "oe-ringer",
    host: str = "Aegis",
    dry_run: bool = False,
    force: bool = False,
    multica_bin: str = "multica",
    poster: Any | None = None,
) -> ReceiptResult:
    """Core entry: post receipt if enabled + issue present. Always fail-open.

    Returns ReceiptResult; never raises for Multica/network failures.
    """
    state = state_dir(state_dir_path)
    if not receipt_enabled():
        return ReceiptResult("disabled", detail="RINGER_MULTICA_RECEIPT=0")

    issue = resolve_issue_id(issue_id)
    if not issue:
        return ReceiptResult("missing_issue", detail="MULTICA_ISSUE_ID unset")

    try:
        if from_last or not run_id:
            run = find_run(state, from_last=True)
            rid = str(run.get("run_id") or "")
        else:
            run = find_run(state, run_id=run_id)
            rid = str(run_id)
    except Exception as exc:
        return ReceiptResult("error", issue_id=issue, detail=f"find_run: {exc}")

    if not rid:
        return ReceiptResult("error", issue_id=issue, detail="run missing run_id")

    posted = load_posted(state)
    if rid in posted and not force:
        return ReceiptResult(
            "skipped",
            run_id=rid,
            issue_id=issue,
            detail="idempotent: already posted",
        )

    rs = ringside_ref(state)
    body = format_receipt_body(
        issue_id=issue,
        run=run,
        ringside=rs,
        lane=lane,
        host=host,
    )
    try:
        if poster is not None:
            result = poster(issue, body, dry_run=dry_run)
        else:
            result = post_multica_comment(
                issue, body, dry_run=dry_run, multica_bin=multica_bin
            )
    except Exception as exc:
        return ReceiptResult(
            "error",
            run_id=rid,
            issue_id=issue,
            detail=f"post exception: {exc}",
        )

    if not result.get("ok"):
        return ReceiptResult(
            "error",
            run_id=rid,
            issue_id=issue,
            detail=(
                f"multica rc={result.get('returncode')}: "
                f"{(result.get('stderr') or result.get('stdout') or '')[:400]}"
            ),
        )

    if not dry_run:
        posted.add(rid)
        try:
            save_posted(state, posted)
        except Exception as exc:
            # Posted remotely but ledger write failed — still report posted;
            # next attempt may duplicate unless operator cleans ledger.
            return ReceiptResult(
                "posted",
                run_id=rid,
                issue_id=issue,
                detail=f"posted but ledger save failed: {exc}",
            )

    return ReceiptResult(
        "dry_run" if dry_run else "posted",
        run_id=rid,
        issue_id=issue,
        detail="dry_run" if dry_run else "ok",
    )


def maybe_post_receipt_for_run(
    run_id: str,
    *,
    state_dir_path: Path | None = None,
    host: str | None = None,
) -> ReceiptResult:
    """In-process hook used by ringer.py after Judge logging completes."""
    return maybe_post_receipt(
        run_id=run_id,
        state_dir_path=state_dir_path,
        host=host or os.environ.get("RINGER_RECEIPT_HOST") or "Aegis",
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--issue", default="")
    ap.add_argument("--run-id")
    ap.add_argument("--from-last", action="store_true")
    ap.add_argument("--lane", default="oe-ringer")
    ap.add_argument("--host", default="Aegis")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="override ~/.ringer (tests / isolated canary)",
    )
    args = ap.parse_args(argv)

    result = maybe_post_receipt(
        run_id=args.run_id,
        from_last=args.from_last or not args.run_id,
        issue_id=args.issue or None,
        state_dir_path=args.state_dir,
        lane=args.lane,
        host=args.host,
        dry_run=args.dry_run,
        force=args.force,
    )
    print(f"{result.status}: run_id={result.run_id} issue={result.issue_id} {result.detail}")
    if result.status == "error":
        return 1
    if result.status == "missing_issue":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
