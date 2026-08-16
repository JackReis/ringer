#!/usr/bin/env python3
"""RingEngineProbe: resolve Ringer engine bins from config.toml, not `which`.

Correct availability check (no PATH false-negatives):
  - Parse <config.toml> with tomllib.
  - For each [engines.NAME], read `bin`.
  - Absolute `bin` -> AVAILABLE if os.path.exists, else MISSING.
  - Bare-name `bin` -> resolve via shutil.which; AVAILABLE if found.
  - Else MISSING.

Exit codes: 0 = all configured engines available; 1 = at least one MISSING;
2 = config file missing/unreadable.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tomllib
from pathlib import Path


def resolve(bin_str: str) -> Path | None:
    """Mirror Ringer's load_engines bin resolution (ringer.py:555-571)."""
    if not bin_str or not bin_str.strip():
        return None
    bin_str = bin_str.strip()
    p = Path(bin_str).expanduser()
    if p.is_absolute():
        return p if p.exists() else None
    which = shutil.which(bin_str)
    return Path(which) if which else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("config", nargs="?", default=None,
                    help="Path to config.toml (default: ~/.config/ringer/config.toml)")
    args = ap.parse_args()

    cfg = (Path(args.config).expanduser() if args.config
           else Path.home() / ".config" / "ringer" / "config.toml")
    if not cfg.is_file():
        print(f"FAIL: config not found: {cfg}", file=sys.stderr)
        return 2

    with cfg.open("rb") as fh:
        data = tomllib.load(fh)

    engines = data.get("engines") or {}
    if not engines:
        print("WARN: no [engines.*] tables in config (nothing to probe)")
        return 0

    rc = 0
    print(f"# Ringer engine probe — {cfg}")
    for name in sorted(engines):
        section = engines[name]
        bin_str = str(section.get("bin", "")).strip() if isinstance(section, dict) else ""
        resolved = resolve(bin_str)
        status = "AVAILABLE" if resolved else "MISSING"
        if not resolved:
            rc = 1
        suffix = f" -> {resolved}" if resolved else ""
        print(f"{status:10} {name:14} bin={bin_str}{suffix}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
