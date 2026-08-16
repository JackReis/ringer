#!/usr/bin/env python3
"""Lint-gate: fail if any configured Ringer engine bin is missing/unresolvable.

Usage: engine-bin-probe.py --config <config.toml>
Exit 0 = all engines resolvable; 1 = at least one MISSING; 2 = config error.
Reuses ring-engine-probe.resolve() semantics.
"""
import argparse
import shutil
import sys
import tomllib
from pathlib import Path


def resolve(bin_str: str):
    if not bin_str or not bin_str.strip():
        return None
    p = Path(bin_str.strip()).expanduser()
    if p.is_absolute():
        return p if p.exists() else None
    w = shutil.which(bin_str.strip())
    return Path(w) if w else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = Path(args.config).expanduser()
    if not cfg.is_file():
        print(f"FAIL: config not found: {cfg}")
        return 2
    with cfg.open("rb") as fh:
        data = tomllib.load(fh)
    engines = data.get("engines") or {}
    missing = []
    for name in sorted(engines):
        sec = engines[name]
        bin_str = str(sec.get("bin", "")).strip() if isinstance(sec, dict) else ""
        if not resolve(bin_str):
            missing.append(name)
            print(f"FAIL: engines.{name}.bin unresolvable: {bin_str!r}")
    if missing:
        print(f"FAIL: {len(missing)} engine(s) missing: {', '.join(missing)}")
        return 1
    print(f"PASS: all {len(engines)} configured engine(s) resolvable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
