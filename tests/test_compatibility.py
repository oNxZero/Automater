import json
import os
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest

from moonlight_studio import compatibility as compat


@pytest.mark.parametrize(
    "environment,expected",
    [
        ({}, "headless"),
        ({"DISPLAY": ":1"}, "x11"),
        ({"WAYLAND_DISPLAY": "wayland-0"}, "wayland"),
        ({"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}, "wayland"),
        ({"XDG_SESSION_TYPE": "x11", "WAYLAND_DISPLAY": "stale", "DISPLAY": ":0"}, "x11"),
        ({"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}, "wayland"),
        ({"XDG_SESSION_TYPE": "tty"}, "headless"),
    ],
)
def test_session_detection_does_not_confuse_xwayland_stale_or_missing_environment(
    environment, expected
):
    assert compat.session_type(environment) == expected


@pytest.mark.parametrize(
    "environment,expected",
    [
        ({"DISPLAY": ":1"}, "xcb"),
        ({"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":1"}, "wayland;xcb"),
        ({"WAYLAND_DISPLAY": "wayland-0"}, "wayland"),
        ({"QT_QPA_PLATFORM": "offscreen"}, "offscreen"),
        ({"QT_QPA_PLATFORM": "xcb", "WAYLAND_DISPLAY": "wayland-0"}, "xcb"),
    ],
)
def test_qt_plugin_selection_prefers_native_display_and_preserves_overrides(environment, expected):
    compat.configure_qt_platform(environment)
    assert environment["QT_QPA_PLATFORM"] == expected


def test_gui_headless_error_points_to_doctor():
    with pytest.raises(RuntimeError, match="--doctor"):
        compat.configure_qt_platform({})


def test_stale_hyprland_variables_cannot_override_an_x11_session(monkeypatch):
    monkeypatch.setattr(compat.shutil, "which", lambda _: "/usr/bin/hyprctl")
    assert not compat.hyprland_available(
        {"XDG_SESSION_TYPE": "x11", "HYPRLAND_INSTANCE_SIGNATURE": "old"}
    )
    assert compat.hyprland_available(
        {"XDG_SESSION_TYPE": "wayland", "HYPRLAND_INSTANCE_SIGNATURE": "active"}
    )


def test_pointer_capability_rejects_headless_and_keeps_wayland_out_of_x11(monkeypatch):
    from moonlight_studio.pointer import capability, desktop_pointer

    for key in ("XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE"):
        monkeypatch.delenv(key, raising=False)
    assert not capability()[0]
    with pytest.raises(RuntimeError, match="No graphical"):
        desktop_pointer()
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("DISPLAY", ":0")
    assert not capability()[0]
    with pytest.raises(RuntimeError, match="RemoteDesktop"):
        desktop_pointer()


def missing_qt(_package):
    raise PackageNotFoundError("PySide6-Essentials")


@pytest.mark.parametrize(
    "machine,release,expected",
    [
        ("x86_64", "2.33", True),
        ("x86_64", "2.34", False),
        ("aarch64", "2.38", True),
        ("aarch64", "2.39", False),
    ],
)
def test_fresh_install_checks_actual_qt_wheel_abi_floor(monkeypatch, machine, release, expected):
    monkeypatch.setattr(compat, "version", missing_qt)
    monkeypatch.setattr(compat.platform, "machine", lambda: machine)
    monkeypatch.setattr(compat.platform, "libc_ver", lambda: ("glibc", release))
    assert bool(compat.launch_issues()) is expected


def test_alpine_style_musl_installs_explain_native_build_requirement(monkeypatch):
    monkeypatch.setattr(compat, "version", missing_qt)
    monkeypatch.setattr(compat.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(compat.platform, "libc_ver", lambda: ("musl", "1.2"))
    assert "musl" in " ".join(compat.launch_issues())


def test_existing_custom_qt_build_is_not_rejected_based_on_wheel_requirements(monkeypatch):
    monkeypatch.setattr(compat, "version", lambda _: "6.11.2")
    monkeypatch.setattr(compat.platform, "libc_ver", lambda: ("glibc", "2.28"))
    assert not compat.launch_issues()


def test_report_separates_wayland_window_restrictions_from_recording(monkeypatch):
    report = compat.environment_report(
        {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "GNOME"}
    )
    assert "Any active window" in report["window_picker"]
    assert "/dev/input" in report["capture"] and "/dev/uinput" in report["desktop_replay"]
    assert "RemoteDesktop" in report["absolute_reset"]
    assert (
        "KDE native" in compat.environment_report({"XDG_CURRENT_DESKTOP": "KDE"})["window_picker"]
    )
    assert compat.kde_desktop({"XDG_SESSION_DESKTOP": "plasma"})
    assert not compat.kde_desktop({"XDG_CURRENT_DESKTOP": "GNOME", "XDG_SESSION_DESKTOP": "plasma"})


def test_doctor_works_without_display_or_qt_platform_initialization():
    env = {**os.environ, "XDG_SESSION_TYPE": "tty"}
    for key in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM", "HYPRLAND_INSTANCE_SIGNATURE"):
        env.pop(key, None)
    result = subprocess.run(
        [sys.executable, "-m", "moonlight_studio.app", "--doctor"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["session"] == "headless" and "compatibility" in report


def test_compatibility_panel_preserves_document_and_does_not_request_permissions(
    qtbot, tmp_path, monkeypatch
):
    from test_gui import clean, window

    from moonlight_studio.portal import PortalConnection

    monkeypatch.setattr(
        PortalConnection,
        "connect_pointer",
        lambda _: pytest.fail("No permission request is allowed"),
    )
    win = window(qtbot, tmp_path, monkeypatch)
    before = win.script().to_dict()
    win.show_compatibility()
    assert win.compatibility_dialog.isVisible()
    assert win.script().to_dict() == before
    assert "Recording" in win.compatibility_dialog.details.toPlainText()
    clean(win)


@pytest.mark.parametrize("configured", ["", "relative/config", "/tmp/absolute-config"])
def test_xdg_config_home_ignores_empty_or_relative_values(monkeypatch, configured):

    from moonlight_studio.storage import data_dir

    monkeypatch.setenv("XDG_CONFIG_HOME", configured)
    root = Path(configured) if configured.startswith("/") else Path.home() / ".config"
    assert data_dir() == root / "moonlight-studio"


@pytest.mark.parametrize("override", [False, True])
def test_launcher_finds_supported_python_and_respects_an_explicit_override(tmp_path, override):
    import shutil

    root = Path(__file__).resolve().parents[1]
    launcher = tmp_path / "start.sh"
    shutil.copy(root / "start.sh", launcher)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    fake = """#!/bin/sh
printf '%s %s\\n' "$(basename "$0")" "$*" >> "$MOONLIGHT_TEST_LOG"
if [ "$1" = "-c" ]; then
    case "$0" in */python3) exit 1;; esac
    exit 0
fi
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
    mkdir -p "$3/bin"
    cp "$0" "$3/bin/python"
    printf '#!/bin/sh\\nprintf "started %%s\\\\n" "$*"\\n' > "$3/bin/moonlight-studio"
    chmod +x "$3/bin/moonlight-studio"
    exit 0
fi
cat >/dev/null
exit 0
"""
    for name in ("python3", "python3.14"):
        path = binaries / name
        path.write_text(fake)
        path.chmod(0o755)
    log = tmp_path / "calls"
    env = {
        **os.environ,
        "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
        "MOONLIGHT_TEST_LOG": str(log),
    }
    env.pop("MOONLIGHT_PYTHON", None)
    if override:
        env["MOONLIGHT_PYTHON"] = str(binaries / "python3")
    result = subprocess.run(
        ["bash", str(launcher), "--doctor"], env=env, capture_output=True, text=True, timeout=10
    )
    if override:
        assert result.returncode != 0 and "Python 3.11+" in result.stderr
        assert not (tmp_path / ".venv").exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "python3.14 -m venv .venv" in log.read_text()
        assert "started --doctor" in result.stdout
