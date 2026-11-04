#!/bin/sh
# The application-menu entry uses this wrapper so paths are shell arguments,
# including installation folders containing spaces, percent signs or equals.
set -eu
cd -- "$(dirname -- "$0")/.."
exec .venv/bin/python -m automater "$@"
