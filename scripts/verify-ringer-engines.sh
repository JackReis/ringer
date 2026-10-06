#!/usr/bin/env bash
# verify-ringer-engines.sh — preflight gate; aborts dispatch on any MISSING engine.
set -euo pipefail
# Self-locating: resolve PROBE/CHECK relative to this script's own directory so
# the canonical clone can live anywhere (e.g. ~/Projects/ringer-fleet-swarm).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROBE="$HERE/ring-engine-probe.py"
CHECK="$HERE/../checks/engine-bin-probe.py"
CONFIG="${1:-$HOME/.config/ringer/config.toml}"
echo "== Preflight: Ringer engine-bin resolution =="
python3 "$PROBE" "$CONFIG" || true
if ! python3 "$CHECK" --config "$CONFIG"; then
  echo "ABORT: engine-bin lint-gate failed — fix config.toml before dispatch." >&2
  exit 1
fi
echo "OK: engine-bin gate passed."
