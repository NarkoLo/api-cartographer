#!/usr/bin/env sh
# Обёртка healthcheck для Linux, macOS и Git Bash.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python "$SCRIPT_DIR/healthcheck.py" "$@"

