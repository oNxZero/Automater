"""Exercise the rename's data migration and real desktop-entry parsing safely."""

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from automater.desktop import APP_ID, data_home, install
from automater.legacy import LEGACY_DIRECTORY, migrate_config
from automater.models import Script, Step
from automater.preferences import Preferences
from automater.storage import prepare_data_dir, save


def test_rename_carries_preferences_recovery_and_library_without_changing_originals(tmp_path):
    original = tmp_path / LEGACY_DIRECTORY
    save(Script("A saved routine", steps=[Step(20)]), original / "scripts/route.json")
    save(Script("Recovered work", steps=[Step(50)]), original / "recovery-first.json")
    preferences = Preferences(script_directory=str(original / "scripts"))
    preferences.recent_scripts = [str(original / "scripts/route.json"), "/other/route.json"]
    preferences.library_folders = [str(original / "scripts")]
    preferences.save(original / "preferences.json")
    data = json.loads((original / "preferences.json").read_text())
    data["theme"] = "studio"
    (original / "preferences.json").write_text(json.dumps(data))
    before = {p.relative_to(original): p.read_bytes() for p in original.rglob("*.json")}
    destination = migrate_config(tmp_path)
    result = Preferences.load(destination / "preferences.json")
    assert result.theme == "automater"
    assert result.script_directory == str(destination / "scripts")
    assert result.recent_scripts == [str(destination / "scripts/route.json"), "/other/route.json"]
    assert result.library_folders == [str(destination / "scripts")]
    assert (destination / "scripts/route.json").read_bytes() == before[Path("scripts/route.json")]
    assert (destination / "recovery-first.json").read_bytes() == before[Path("recovery-first.json")]
    assert destination.stat().st_mode & 0o777 == 0o700
    assert {p.relative_to(original): p.read_bytes() for p in original.rglob("*.json")} == before
    (destination / "preferences.json").write_text("newer content")
    assert migrate_config(tmp_path) == destination
    assert (destination / "preferences.json").read_text() == "newer content"


def test_failed_migration_keeps_original_and_does_not_publish_partial_config(tmp_path, monkeypatch):
    original = tmp_path / LEGACY_DIRECTORY
    original.mkdir()
    (original / "preferences.json").write_text("original")

    def fail(*args, **kwargs):
        raise OSError("Disk full")

    monkeypatch.setattr(shutil, "copytree", fail)
    with pytest.raises(OSError, match="Disk full"):
        migrate_config(tmp_path)
    assert (original / "preferences.json").read_text() == "original"
    assert list(tmp_path.iterdir()) == [original]


def test_config_discovery_migrates_only_the_selected_xdg_root(tmp_path, monkeypatch):
    original = tmp_path / LEGACY_DIRECTORY
    original.mkdir()
    (original / "recovery.json").write_text("retained")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert prepare_data_dir() == tmp_path / "automater"
    assert (prepare_data_dir() / "recovery.json").read_text() == "retained"


@pytest.mark.parametrize("configured", ["", "relative"])
def test_desktop_integration_respects_xdg_default(monkeypatch, configured):
    monkeypatch.setenv("XDG_DATA_HOME", configured)
    assert data_home() == Path.home() / ".local/share"


@pytest.mark.parametrize(
    "name", ["Automater", 'User\'s apps = 100% $dollar `literal` \\"quoted\\"']
)
def test_desktop_launcher_opens_exact_interpreter_and_directory(tmp_path, name):
    gio = shutil.which("gio")
    if not gio:
        pytest.skip("GIO is unavailable")
    checkout = tmp_path / name
    (checkout / ".venv/bin").mkdir(parents=True)
    (checkout / ".venv/bin/python").symlink_to(sys.executable)
    (checkout / "scripts").mkdir()
    shutil.copy(
        Path(__file__).resolve().parents[1] / "scripts/launch.sh", checkout / "scripts/launch.sh"
    )
    (checkout / "src/automater/assets").mkdir(parents=True)
    (checkout / "src/automater/assets/automater.svg").write_text("<svg/>")
    output = tmp_path / "launched.json"
    (checkout / "automater.py").write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['AUTOMATER_TEST_RESULT']).write_text(json.dumps([os.getcwd(), sys.argv[1:]]))\n"
    )
    entry = install(checkout, tmp_path / "menu")
    assert entry.name == APP_ID + ".desktop"
    validator = shutil.which("desktop-file-validate")
    if validator:
        result = subprocess.run([validator, str(entry)], capture_output=True, text=True, timeout=5)
        assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run(
        [gio, "launch", str(entry)],
        env={
            **os.environ,
            "AUTOMATER_TEST_RESULT": str(output),
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent-automater-test",
        },
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    deadline = time.monotonic() + 5
    while not output.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert output.exists(), result.stdout + result.stderr
    assert json.loads(output.read_text()) == [str(checkout), []]
    assert "Name=Automater" in entry.read_text() and "--demo" in entry.read_text()


def test_shortcut_remove_keeps_settings_and_other_entries(tmp_path):
    menu = tmp_path / "applications"
    menu.mkdir()
    (menu / f"{APP_ID}.desktop").write_text("placeholder")
    (menu / "other.desktop").write_text("other")
    config = tmp_path / "config/automater"
    config.mkdir(parents=True)
    (config / "recovery.json").write_text("keep")
    result = subprocess.run(
        [sys.executable, "-m", "automater.desktop", "--remove"],
        env={
            **os.environ,
            "XDG_DATA_HOME": str(tmp_path),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
        },
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert not (menu / f"{APP_ID}.desktop").exists()
    assert (menu / "other.desktop").read_text() == "other"
    assert (config / "recovery.json").read_text() == "keep"


@pytest.mark.parametrize("startup_result", [0, 42])
def test_installer_registers_only_after_runtime_setup_succeeds(tmp_path, startup_result):
    if os.geteuid() == 0:
        pytest.skip("The installer intentionally refuses root; CI runs this as a desktop user")
    root = Path(__file__).resolve().parents[1]
    checkout = tmp_path / "Automater install"
    (checkout / ".venv/bin").mkdir(parents=True)
    shutil.copy(root / "install.sh", checkout / "install.sh")
    shutil.copytree(root / "src/automater/assets", checkout / "src/automater/assets")
    (checkout / "scripts").mkdir()
    shutil.copy(root / "scripts/launch.sh", checkout / "scripts/launch.sh")
    interpreter = checkout / ".venv/bin/python"
    interpreter.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + ' "$@"\n')
    interpreter.chmod(0o755)
    launcher = checkout / "start.sh"
    launcher.write_text(f'#!/bin/sh\n[ "$1" = "--doctor" ] || exit 99\nexit {startup_result}\n')
    launcher.chmod(0o755)
    result = subprocess.run(
        [
            "bash",
            str(checkout / "install.sh"),
            "--no-system-packages",
            "--no-input-permissions",
        ],
        env={**os.environ, "XDG_DATA_HOME": str(tmp_path / "xdg")},
        capture_output=True,
        text=True,
        timeout=10,
    )
    entry = tmp_path / "xdg/applications" / f"{APP_ID}.desktop"
    if startup_result:
        assert result.returncode == startup_result
        assert not entry.exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert entry.is_file() and "Search for Automater" in result.stdout
        assert str(checkout) in entry.read_text()
