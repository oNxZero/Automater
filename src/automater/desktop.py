"""Per-user application-menu integration, without importing Qt or touching input."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_ID = "io.github.onxzero.Automater"


def string_value(value):
    value = str(value)
    if any(char in value for char in "\n\r\0"):
        raise ValueError("Desktop paths cannot contain newlines or null characters")
    return value.replace("\\", "\\\\").replace("\t", "\\t")


def exec_argument(value):
    value = str(value)
    if any(char in value for char in "\n\r\0"):
        raise ValueError("Desktop paths cannot contain newlines or null characters")
    # Desktop Entry string escaping is applied before Exec argument quoting.
    value = value.replace("%", "%%")
    for char in ("\\", '"', "`", "$"):
        value = value.replace(char, "\\" + char)
    return '"' + value.replace("\\", "\\\\") + '"'


def data_home():
    configured = os.environ.get("XDG_DATA_HOME", "")
    return (
        Path(configured)
        if configured and Path(configured).is_absolute()
        else Path.home() / ".local/share"
    )


def entry_text(checkout):
    checkout = Path(checkout).resolve()
    interpreter = checkout / ".venv/bin/python"
    launcher = checkout / "scripts/launch.sh"
    icon = checkout / "src/automater/assets/automater.svg"
    if not interpreter.is_file() or not launcher.is_file() or not icon.is_file():
        raise ValueError("Run install.sh from a complete checkout with its .venv installed")
    command = "/bin/sh " + exec_argument(launcher)
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Automater\n"
        "GenericName=Input recorder and workflow editor\n"
        "Comment=Record, edit and replay keyboard and mouse workflows\n"
        f"Exec={command}\n"
        f"Path={string_value(checkout)}\n"
        f"Icon={string_value(icon)}\n"
        "Terminal=false\n"
        "Categories=Utility;\n"
        "Keywords=automation;macro;keyboard;mouse;workflow;\n"
        f"StartupWMClass={APP_ID}\n"
        "Actions=Demo;\n\n"
        "[Desktop Action Demo]\n"
        "Name=Try the example (no input sent)\n"
        f"Exec={command} --demo\n"
    )


def install(checkout, destination=None):
    content = entry_text(checkout)
    destination = Path(destination) if destination else data_home() / "applications"
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"{APP_ID}.desktop"
    # Use a sibling temporary file so a failed replacement keeps the old entry.
    import tempfile

    fd, temporary = tempfile.mkstemp(prefix=".automater-", dir=destination)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


def main():
    parser = argparse.ArgumentParser(description="Automater application-menu shortcut")
    parser.add_argument("--checkout", type=Path)
    parser.add_argument("--remove", action="store_true", help="Remove only the menu shortcut")
    args = parser.parse_args()
    try:
        if args.remove:
            path = data_home() / "applications" / f"{APP_ID}.desktop"
            path.unlink(missing_ok=True)
            print("Removed Automater's menu shortcut. Workflows and settings were kept.")
        else:
            if not args.checkout:
                parser.error("--checkout is required when installing")
            print(install(args.checkout))
        updater = shutil.which("update-desktop-database")
        if updater:
            subprocess.run([updater, str(data_home() / "applications")], check=False)
    except (OSError, ValueError) as exc:
        print(f"Could not update Automater's menu shortcut: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
