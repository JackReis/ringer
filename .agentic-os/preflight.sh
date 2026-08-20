#!/usr/bin/env bash
set -u

failures=0
require_path() {
  local label="$1" path="$2"
  if [[ -z "$path" ]]; then
    printf 'FAIL %s is not set; launch from the root Hermes environment.\n' "$label" >&2
    failures=$((failures + 1))
  elif [[ ! -e "$path" ]]; then
    printf 'FAIL %s points to a missing path: %s\n' "$label" "$path" >&2
    failures=$((failures + 1))
  else
    printf 'ok %s\n' "$label"
  fi
}

require_path HERMES_HOME "${HERMES_HOME:-}"
require_path HERMES_CONFIG_PATH "${HERMES_CONFIG_PATH:-}"

if [[ -n "${PAPERCLIP_API_URL:-}" ]]; then
  printf 'ok PAPERCLIP_API_URL\n'
else
  printf 'WARN PAPERCLIP_API_URL is unset; the canonical launcher will use its safe local default.\n'
fi

if [[ ! -x "/Users/hermes/.local/bin/hermes-agent" ]]; then
  printf 'FAIL canonical Hermes executable is unavailable: /Users/hermes/.local/bin/hermes-agent\n' >&2
  failures=$((failures + 1))
else
  printf 'ok canonical Hermes executable\n'
fi

if [[ ! -f "/Users/hermes/Projects/agentic-os/scripts/smoke-hermes-paperclip.cjs" ]]; then
  printf 'FAIL canonical launcher reference is unavailable: /Users/hermes/Projects/agentic-os/scripts/smoke-hermes-paperclip.cjs\n' >&2
  failures=$((failures + 1))
else
  printf 'ok canonical launcher reference\n'
fi

if (( failures > 0 )); then
  printf 'Preflight failed with %d blocking issue(s).\n' "$failures" >&2
  exit 1
fi
printf 'Preflight passed; project remains within the root environment boundary.\n'
