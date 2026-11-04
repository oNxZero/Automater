"""One-time compatibility with settings written before the Automater rename.

Old identifiers live here only; new files and integration use Automater names.
"""

import json
import shutil
import tempfile
from pathlib import Path

LEGACY_DIRECTORY = "moonlight-studio"
LEGACY_VIRTUAL_NAMES = ("Moonlight Studio", "Moonlight HID")
LEGACY_SELECTION = "moonlight-selection"


def migrate_config(root):
    """Copy once, publish atomically, and leave the original settings untouched."""
    root = Path(root)
    destination = root / "automater"
    original = root / LEGACY_DIRECTORY
    if destination.exists() or not original.is_dir():
        return destination
    staging = Path(tempfile.mkdtemp(prefix=".automater-migration-", dir=root))
    try:
        shutil.copytree(original, staging, dirs_exist_ok=True, symlinks=True)
        staging.chmod(0o700)
        preferences = staging / "preferences.json"
        if preferences.is_file() and not preferences.is_symlink():
            try:
                data = json.loads(preferences.read_text())
                if isinstance(data, dict):
                    for key in ("script_directory", "recent_scripts", "library_folders"):
                        value = data.get(key)

                        def relocate(path):
                            if not isinstance(path, str):
                                return path
                            try:
                                relative = Path(path).relative_to(original)
                            except ValueError:
                                return path
                            return str(destination / relative)

                        if isinstance(value, list):
                            data[key] = [relocate(path) for path in value]
                        elif isinstance(value, str):
                            data[key] = relocate(value)
                    from .storage import write_json

                    write_json(data, preferences)
            except (ValueError, UnicodeError):
                # Let the regular preference loader explain invalid settings.
                pass
        try:
            staging.rename(destination)
        except OSError:
            if not destination.is_dir():
                raise
        return destination
    finally:
        shutil.rmtree(staging, ignore_errors=True)
