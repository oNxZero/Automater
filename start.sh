#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/moonlight-studio ]]; then
    python3 -m venv .venv
    .venv/bin/python -m pip install -c requirements.lock -e .
fi
exec .venv/bin/moonlight-studio "$@"
