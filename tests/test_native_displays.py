"""Boot Qt on private native displays; never connect input to the host session."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_gui(env, platform):
    env = {**env, "QT_DEBUG_PLUGINS": "1"}
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/smoke_gui.py")],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout.strip().splitlines()[-1])
    assert output == {"platform": platform, "visible": True, "rendered": True}


def test_native_xcb_gui_on_a_private_x_server(tmp_path):
    binary = shutil.which("Xvfb")
    if not binary:
        pytest.skip("Xvfb is unavailable")
    with (tmp_path / "display").open("w+") as output:
        server = subprocess.Popen(
            [
                binary,
                "-displayfd",
                str(output.fileno()),
                "-screen",
                "0",
                "1280x800x24",
                "-nolisten",
                "tcp",
            ],
            pass_fds=(output.fileno(),),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 5
            display = ""
            while not display and time.monotonic() < deadline and server.poll() is None:
                output.seek(0)
                display = output.read().strip()
                time.sleep(0.02)
            assert display, "Private X server did not start"
            env = {
                **os.environ,
                "DISPLAY": ":" + display,
                "XDG_SESSION_TYPE": "x11",
                "QT_QPA_PLATFORM": "xcb",
            }
            env.pop("WAYLAND_DISPLAY", None)
            run_gui(env, "xcb")
        finally:
            server.terminate()
            server.wait(timeout=5)


def test_native_wayland_gui_on_headless_weston(tmp_path):
    binary = shutil.which("weston")
    if not binary:
        pytest.skip("Weston is unavailable")
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    log = tmp_path / "weston.log"
    env = {
        **os.environ,
        "XDG_RUNTIME_DIR": str(runtime),
        "XDG_SESSION_TYPE": "wayland",
        "WAYLAND_DISPLAY": "moonlight-test",
        "QT_QPA_PLATFORM": "wayland",
    }
    env.pop("DISPLAY", None)
    server = subprocess.Popen(
        [
            binary,
            "--no-config",
            "--backend=headless-backend.so",
            "--renderer=pixman",
            "--socket=moonlight-test",
            "--idle-time=0",
            "--width=1280",
            "--height=800",
            "--log=" + str(log),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 5
        while (
            not (runtime / "moonlight-test").exists()
            and time.monotonic() < deadline
            and server.poll() is None
        ):
            time.sleep(0.02)
        assert (runtime / "moonlight-test").exists(), (
            log.read_text() if log.exists() else "Weston did not start"
        )
        run_gui(env, "wayland")
    finally:
        server.terminate()
        server.wait(timeout=5)
