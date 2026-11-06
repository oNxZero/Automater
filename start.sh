#!/usr/bin/env bash
set -euo pipefail
launch_dir="$PWD"
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
checkout_dir="$PWD"
if [[ ! -x .venv/bin/python ]]; then
    runtime_python=""
    candidates=(python3 python3.14 python3.13 python3.12 python3.11)
    if [[ -n "${AUTOMATER_PYTHON:-}" ]]; then
        candidates=("$AUTOMATER_PYTHON")
    fi
    for candidate in "${candidates[@]}"; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
            runtime_python="$candidate"
            break
        fi
    done
    if [[ -z "$runtime_python" ]]; then
        echo "Automater needs Python 3.11+. Install a supported Python or set AUTOMATER_PYTHON to its executable." >&2
        exit 1
    fi
    "$runtime_python" -m venv .venv || { echo "Could not create .venv. Install your distro's Python venv package; see docs/INSTALL.md." >&2; exit 1; }
fi
if ! .venv/bin/python -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    echo "Existing .venv uses an unsupported Python. Rename it, then relaunch with AUTOMATER_PYTHON=python3.11 (or newer)." >&2
    exit 1
fi
.venv/bin/python - <<'PY'
import sys
sys.path.insert(0, "src")
from automater.compatibility import launch_issues
issues = launch_issues()
if issues:
    print("Cannot install the standard runtime:", *issues, sep="\n", file=sys.stderr)
    sys.exit(1)
PY
# Refresh installed dependencies after an update, without network work on every launch.
if ! .venv/bin/python - <<'PY'
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
from pathlib import Path
import sys
import tomllib

try:
    expected = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
    valid = version("automater") == expected
    installed = find_spec("automater")
    valid = valid and installed is not None and installed.origin is not None
    valid = valid and Path(installed.origin).resolve() == Path("src/automater/__init__.py").resolve()
    for line in Path("requirements.lock").read_text().splitlines():
        if "==" in line and not line.lstrip().startswith("#"):
            package, expected = line.strip().split("==", 1)
            valid = valid and version(package) == expected
except PackageNotFoundError:
    valid = False
sys.exit(0 if valid else 1)
PY
then
    echo "Updating Automater dependencies…"
    .venv/bin/python -m pip install -c requirements.lock -e .
fi
cd -- "$launch_dir"
exec "$checkout_dir/.venv/bin/automater" "$@"
