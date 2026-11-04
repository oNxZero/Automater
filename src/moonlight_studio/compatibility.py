"""Read-only Linux feature reporting. Importable before Qt/evdev are installed."""

import os
import platform
import shutil
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def session_type(environ=None):
    env = os.environ if environ is None else environ
    declared = env.get("XDG_SESSION_TYPE", "").lower()
    if declared in ("x11", "wayland"):
        return declared
    if env.get("WAYLAND_DISPLAY"):
        return "wayland"
    if env.get("DISPLAY"):
        return "x11"
    return "headless"


def desktop_name(environ=None):
    env = os.environ if environ is None else environ
    return env.get("XDG_CURRENT_DESKTOP") or env.get("XDG_SESSION_DESKTOP") or "Unknown desktop"


def kde_desktop(environ=None):
    return any(name in desktop_name(environ).upper() for name in ("KDE", "PLASMA"))


def configure_qt_platform(environ=None):
    env = os.environ if environ is None else environ
    if env.get("QT_QPA_PLATFORM"):
        return
    session = session_type(env)
    if session == "wayland":
        env["QT_QPA_PLATFORM"] = "wayland;xcb" if env.get("DISPLAY") else "wayland"
    elif session == "x11":
        env["QT_QPA_PLATFORM"] = "xcb"
    else:
        raise RuntimeError(
            "No graphical desktop detected. Start Studio inside X11/Wayland, or use --doctor for headless diagnostics."
        )


def hyprland_available(environ=None):
    env = os.environ if environ is None else environ
    return (
        session_type(env) == "wayland"
        and bool(env.get("HYPRLAND_INSTANCE_SIGNATURE"))
        and bool(shutil.which("hyprctl"))
    )


def launch_issues():
    issues = []
    if sys.version_info < (3, 11):
        issues.append("Python 3.11 or newer is required.")
    try:
        version("PySide6-Essentials")
    except PackageNotFoundError:
        machine = platform.machine().lower()
        if machine not in ("x86_64", "aarch64"):
            issues.append(
                "The official Qt wheels target x86_64/aarch64. This architecture needs a compatible native Qt/PySide build."
            )
        libc, release = platform.libc_ver()
        if libc == "glibc":
            minimum = (2, 39) if machine == "aarch64" else (2, 34)
            try:
                actual = tuple(int(part) for part in release.split(".")[:2])
            except ValueError:
                actual = minimum
            if actual < minimum:
                issues.append(
                    f"The pinned Qt wheel requires glibc {minimum[0]}.{minimum[1]}+ on {machine}; detected {release}. Use a newer system or a compatible native build."
                )
        elif libc == "musl" or any(Path("/lib").glob("ld-musl-*.so.1")):
            issues.append(
                "The pinned Qt wheels use glibc. Alpine/musl requires a compatible native Qt/PySide build; the standard pip install cannot provide it."
            )
    return issues


def environment_report(environ=None):
    env = os.environ if environ is None else environ
    session = session_type(env)
    desktop = desktop_name(env)
    try:
        distro = platform.freedesktop_os_release().get("PRETTY_NAME", "Linux")
    except OSError:
        distro = "Linux"
    try:
        qt = version("PySide6-Essentials")
    except PackageNotFoundError:
        qt = "not installed"
    native = kde_desktop(env)
    display = bool(env.get("DISPLAY"))
    reset = (
        "X11 pointer"
        if session == "x11" and display
        else "Hyprland pointer"
        if hyprland_available(env)
        else "RemoteDesktop portal permission required"
        if session == "wayland"
        else "No graphical session"
    )
    return {
        "distribution": distro,
        "architecture": platform.machine(),
        "libc": " ".join(platform.libc_ver()).strip() or "unknown",
        "python": platform.python_version(),
        "qt": qt,
        "session": session,
        "desktop": desktop,
        "x11_display": display,
        "wayland_display": bool(env.get("WAYLAND_DISPLAY")),
        "qt_platform_override": env.get("QT_QPA_PLATFORM", "automatic"),
        "capture": "Readable /dev/input/event* devices required",
        "desktop_replay": "Writable /dev/uinput required",
        "absolute_reset": reset,
        "window_picker": "KDE native windows and X11 clients"
        if native
        else "X11/Xwayland clients only; native Wayland apps can use Any active window",
        "background_windows": "X11/Xwayland messages only; game acceptance varies"
        if display
        else "No X11 display; native Wayland background routing unavailable",
        "gamescope": bool(shutil.which("gamescope")),
        "portal": "Not checked; use Check pointer portal (does not request permission)",
        "runtime_issues": launch_issues(),
    }


def feature_summary(report):
    return (
        f"{report['distribution']} · {report['desktop']} · {report['session'].upper()}\n\n"
        f"Python {report['python']} · Qt {report['qt']} · {report['architecture']} · {report['libc']}\n\n"
        "Editing / Test mode: no input permissions needed.\n"
        f"Recording: {report['capture']}.\n"
        f"Desktop playback: {report['desktop_replay']}.\n"
        f"Cursor reset: {report['absolute_reset']}.\n"
        f"Window selection: {report['window_picker']}.\n"
        f"Background input: {report['background_windows']}.\n"
        "A working screenshot/screen-sharing portal does not necessarily provide pointer control."
    )
