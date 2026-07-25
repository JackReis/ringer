#!/usr/bin/env python3
"""Aggregate token usage from a read-only SQLite sessions database."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Sequence


REQUIRED_COLUMNS = {
    "id",
    "model",
    "started_at",
    "input_tokens",
    "output_tokens",
    "billing_provider",
    "estimated_cost_usd",
}
SECONDS_PER_DAY = 24 * 60 * 60
COST_QUANTUM = Decimal("0.000001")


class UsageError(Exception):
    """Raised for clean CLI failures caused by inputs or schema shape."""


@dataclass
class ModelUsage:
    """Accumulates token and cost totals for one model."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost: Decimal = Decimal("0")


@dataclass
class ProviderUsage:
    """Accumulates token, cost, session, and model totals for one provider."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost: Decimal = Decimal("0")
    session_count: int = 0
    models: dict[str, ModelUsage] = field(default_factory=dict)

    def add(self, model: str, input_tokens: int, output_tokens: int, cost: Decimal) -> None:
        """Add one included session row to this provider."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost += cost
        self.session_count += 1

        model_usage = self.models.setdefault(model, ModelUsage())
        model_usage.input_tokens += input_tokens
        model_usage.output_tokens += output_tokens
        model_usage.cost += cost


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Aggregate token usage into rolling 24h and UTC month JSON reports."
    )
    parser.add_argument("--db", required=True, help="Path to the SQLite database.")
    parser.add_argument("--out-24h", required=True, help="Output path for the rolling 24h JSON.")
    parser.add_argument("--out-month", required=True, help="Output path for the current UTC month JSON.")
    parser.add_argument(
        "--now",
        help="Optional deterministic current time as an ISO UTC timestamp, e.g. 2026-07-14T12:00:00Z.",
    )
    return parser.parse_args(argv)


def parse_utc_datetime(value: str) -> datetime:
    """Parse an ISO timestamp and require UTC."""
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise UsageError("--now must be a valid ISO UTC timestamp") from exc

    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise UsageError("--now must include a UTC timezone")
    return parsed.astimezone(timezone.utc)


def format_utc(value: datetime) -> str:
    """Format a UTC datetime as a stable ISO timestamp."""
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_name(value: Any) -> str:
    """Normalize provider or model names, using unknown for blank values."""
    if value is None:
        return "unknown"
    normalized = str(value).strip()
    return normalized if normalized else "unknown"


def coerce_int(value: Any) -> int:
    """Coerce a nullable SQLite token value to an integer."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise UsageError("incompatible sessions data: token columns must contain integers")
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return 0
        try:
            return int(stripped)
        except ValueError as exc:
            raise UsageError("incompatible sessions data: token columns must contain integers") from exc
    raise UsageError("incompatible sessions data: token columns must contain integers")


def coerce_cost(value: Any) -> Decimal:
    """Coerce a nullable SQLite cost value to Decimal."""
    if value is None:
        return Decimal("0")
    if isinstance(value, str) and not value.strip():
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise UsageError("incompatible sessions data: cost column must contain numbers") from exc


def rounded_cost(value: Decimal) -> float:
    """Round a Decimal cost to six fractional digits for JSON output."""
    return float(value.quantize(COST_QUANTUM, rounding=ROUND_HALF_UP))


def connect_read_only(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite database in read-only URI mode."""
    if not db_path.exists():
        raise UsageError(f"database not found: {db_path}")
    if not db_path.is_file():
        raise UsageError(f"database path is not a file: {db_path}")

    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def validate_schema(conn: sqlite3.Connection) -> None:
    """Validate that the sessions table and required columns exist."""
    table_row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sessions'"
    ).fetchone()
    if table_row is None:
        raise UsageError("missing sessions table")

    columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    missing = sorted(REQUIRED_COLUMNS - columns)
    if missing:
        raise UsageError(
            "incompatible sessions schema: missing required columns: " + ", ".join(missing)
        )


def aggregate_window(conn: sqlite3.Connection, start_epoch: float, end_epoch: float) -> dict[str, ProviderUsage]:
    """Aggregate included session rows for one closed time window."""
    providers: dict[str, ProviderUsage] = {}
    rows = conn.execute(
        """
        SELECT id, model, started_at, input_tokens, output_tokens, billing_provider, estimated_cost_usd
        FROM sessions
        WHERE started_at >= ? AND started_at <= ?
        """,
        (start_epoch, end_epoch),
    )

    for row in rows:
        _session_id, model_value, _started_at, input_value, output_value, provider_value, cost_value = row
        input_tokens = coerce_int(input_value)
        output_tokens = coerce_int(output_value)
        cost = coerce_cost(cost_value)

        if input_tokens == 0 and output_tokens == 0 and cost == 0:
            continue

        provider = normalize_name(provider_value)
        model = normalize_name(model_value)
        providers.setdefault(provider, ProviderUsage()).add(model, input_tokens, output_tokens, cost)

    return providers


def serialize_providers(providers: dict[str, ProviderUsage]) -> dict[str, Any]:
    """Serialize provider accumulators in deterministic lexicographic order."""
    serialized: dict[str, Any] = {}
    for provider_name in sorted(providers):
        provider = providers[provider_name]
        models: dict[str, Any] = {}
        for model_name in sorted(provider.models):
            model = provider.models[model_name]
            models[model_name] = {
                "input": int(model.input_tokens),
                "output": int(model.output_tokens),
                "cost": rounded_cost(model.cost),
            }

        serialized[provider_name] = {
            "total_input_tokens": int(provider.input_tokens),
            "total_output_tokens": int(provider.output_tokens),
            "total_estimated_cost_usd": rounded_cost(provider.cost),
            "session_count": int(provider.session_count),
            "models": models,
        }

    return serialized


def build_payload(
    window_start: datetime,
    window_end: datetime,
    providers: dict[str, ProviderUsage],
    generated_at: datetime,
) -> dict[str, Any]:
    """Build one JSON payload with the required top-level keys."""
    return {
        "window": {
            "start": format_utc(window_start),
            "end": format_utc(window_end),
        },
        "providers": serialize_providers(providers),
        "generated_at": format_utc(generated_at),
    }


def fsync_parent(parent: Path) -> None:
    """Best-effort fsync of a parent directory after atomic replacement."""
    try:
        fd = os.open(parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically, creating parent directories first."""
    parent = path.parent if str(path.parent) else Path(".")
    parent.mkdir(parents=True, exist_ok=True)

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        fsync_parent(parent)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def run(args: argparse.Namespace) -> None:
    """Run aggregation and write both output files."""
    now = parse_utc_datetime(args.now) if args.now else datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    day_start_epoch = now.timestamp() - SECONDS_PER_DAY
    month_start_epoch = month_start.timestamp()
    end_epoch = now.timestamp()

    with connect_read_only(Path(args.db)) as conn:
        validate_schema(conn)
        day_providers = aggregate_window(conn, day_start_epoch, end_epoch)
        month_providers = aggregate_window(conn, month_start_epoch, end_epoch)

    day_start = datetime.fromtimestamp(day_start_epoch, tz=timezone.utc)
    day_payload = build_payload(day_start, now, day_providers, now)
    month_payload = build_payload(month_start, now, month_providers, now)

    write_json_atomic(Path(args.out_24h), day_payload)
    write_json_atomic(Path(args.out_month), month_payload)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        run(args)
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except sqlite3.Error:
        print("error: failed to read SQLite database", file=sys.stderr)
        return 2
    except OSError as exc:
        detail = exc.strerror or str(exc)
        print(f"error: file operation failed: {detail}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
