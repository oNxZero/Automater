#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/moonlight-studio ]]; then
    python3 -m venv .venv
fi
# Refresh installed dependencies after an update, without network work on every launch.
if ! .venv/bin/python - <<'PY'
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import sys
import tomllib

try:
    expected = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
    valid = version("moonlight-studio") == expected
    for line in Path("requirements.lock").read_text().splitlines():
        if "==" in line and not line.lstrip().startswith("#"):
            package, expected = line.strip().split("==", 1)
            valid = valid and version(package) == expected
except PackageNotFoundError:
    valid = False
sys.exit(0 if valid else 1)
PY
then
    echo "Updating Moonlight Studio dependencies…"
    .venv/bin/python -m pip install -c requirements.lock -e .
fi
exec .venv/bin/moonlight-studio "$@"
