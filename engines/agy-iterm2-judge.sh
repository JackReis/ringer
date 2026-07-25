#!/bin/bash
# Ringer engine launcher: drive `agy` as an interactive iTerm2 judge.
#
# Pins the dedicated venv interpreter that has the `iterm2` module installed
# (the default system python3 does NOT import iterm2). All args are forwarded
# unchanged to the Python wrapper. Ringer invokes this with cwd = the task dir
# and stdin closed; the wrapper needs the GUI/iTerm2 API, so it must run
# UNSANDBOXED (the config sets empty sandbox/full-access args).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd -P)"
VENV_PY="$HERE/agy-iterm2-venv/bin/python"

if [ ! -x "$VENV_PY" ]; then
  echo "agy-iterm2-judge.sh: venv python missing at $VENV_PY" >&2
  echo "Recreate it: python3 -m venv \"$HERE/agy-iterm2-venv\" && \"$VENV_PY\" -m pip install iterm2" >&2
  exit 127
fi

exec "$VENV_PY" "$HERE/agy-iterm2-judge.py" "$@" < /dev/null
