#!/bin/sh
# Ringer integration; the independently licensed adapter supplies Cursor execution.
set -eu
exec python3 "$(dirname "$0")/cursor-wrapper.py" cloud "$@"
