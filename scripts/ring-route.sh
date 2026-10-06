#!/usr/bin/env bash
# ring-route.sh — pick the right host+engine for a lane, failing closed on probe.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROBE="$HERE/ring-engine-probe.py"
if ssh -o BatchMode=yes hermes@100.84.253.97 "python3 /Users/hermes/ringer/scripts/ring-engine-probe.py /Users/hermes/.config/ringer/config.toml" >/dev/null 2>&1; then
  echo "ROUTE=aegis-ringer"          # native Ringer on Aegis
elif python3 "$PROBE" ~/.config/ringer/config.toml >/dev/null 2>&1; then
  echo "ROUTE=talaris-ringer"        # native Ringer on Talaris
else
  echo "ROUTE=delegate_task (FALLBACK)"   # only after probe proves no native engine
fi
