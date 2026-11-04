"""All XTEST events go to a new, test-owned Xvfb server, never the host display."""

import io
import os
import select
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from Xlib import X, display

from automater.isolated import (
    GameSession,
    IsolatedBackend,
    SessionAddress,
    SessionRPC,
    application_command,
)
from automater.isolated_worker import InputHandler, InputServer, validate_environment
from automater.models import Step
from automater.x11 import WindowInfo, identity


@pytest.fixture
def owned_display():
    binary = shutil.which("Xvfb")
    if binary is None:
        pytest.skip("Xvfb is needed for private-display input integration")
    read_fd, write_fd = os.pipe()
    process = subprocess.Popen(
        [
            binary,
            "-displayfd",
            str(write_fd),
            "-screen",
            "0",
            "1280x720x24",
            "-nolisten",
            "tcp",
            "-noreset",
            "-ac",
        ],
        pass_fds=(write_fd,),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    os.close(write_fd)
    try:
        ready, _, _ = select.select([read_fd], [], [], 5)
        assert ready, "Private Xvfb did not become ready"
        number = os.read(read_fd, 128).decode().strip()
        assert number.isdigit()
        yield ":" + number
    finally:
        os.close(read_fd)
        process.terminate()
        process.wait(timeout=3)
        process.stderr.close()


@pytest.fixture
def game_receiver(owned_display):
    connection = display.Display(owned_display)
    root = connection.screen().root
    window = root.create_window(
        20,
        30,
        600,
        400,
        0,
        connection.screen().root_depth,
        event_mask=X.KeyPressMask
        | X.KeyReleaseMask
        | X.ButtonPressMask
        | X.ButtonReleaseMask
        | X.PointerMotionMask,
    )
    window.set_wm_name("Test game")
    window.set_wm_class("automater-private-test", "AutomaterPrivateTest")
    window.map()
    connection.sync()
    pid, wm_class = identity(connection, window)
    target = WindowInfo(window.id, "Test game", pid, wm_class)
    with tempfile.TemporaryDirectory(prefix="automater-rpc-") as directory:
        address = SessionAddress(str(Path(directory) / "input.sock"), "test-nonce")
        server = InputServer(address.socket_path, InputHandler)
        server.display_name = owned_display
        server.nonce = address.nonce
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield connection, window, address, target
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
    window.destroy()
    connection.sync()
    connection.close()


def received(connection):
    connection.sync()
    events = []
    while connection.pending_events():
        event = connection.next_event()
        if event.type in (X.KeyPress, X.KeyRelease, X.ButtonPress, X.ButtonRelease, X.MotionNotify):
            events.append(event)
    return events


def test_private_game_input_has_its_own_pointer_focus_and_real_events(game_receiver, monkeypatch):
    connection, window, address, target = game_receiver
    # The public backend must not open any X display itself.
    monkeypatch.setattr("automater.isolated.display", None, raising=False)
    backend = IsolatedBackend(address, target)
    try:
        backend.prepare_start((100, 120))
        backend.begin_cycle((100, 120))
        received(connection)
        backend.send(Step(0, "key_down", "KEY_A"))
        backend.send(Step(0, "key_up", "KEY_A"))
        backend.send(Step(0, "move", x=5, y=-3))
        backend.send(Step(0, "key_down", "BTN_LEFT"))
        backend.send(Step(0, "key_up", "BTN_LEFT"))
        events = received(connection)
        assert [event.type for event in events] == [
            X.KeyPress,
            X.KeyRelease,
            X.MotionNotify,
            X.ButtonPress,
            X.ButtonRelease,
        ]
        assert all(not event.send_event for event in events)
        pointer = connection.screen().root.query_pointer()
        assert (pointer.root_x, pointer.root_y) == (125, 147)
        assert connection.get_input_focus().focus.id == window.id
    finally:
        backend.close()


def test_private_session_rejects_wrong_nonce_and_changed_window(game_receiver):
    connection, window, address, target = game_receiver
    rpc = SessionRPC(SessionAddress(address.socket_path, "wrong"))
    try:
        with pytest.raises(RuntimeError, match="identity"):
            rpc.call("windows")
    finally:
        rpc.close()
    backend = IsolatedBackend(address, target)
    try:
        window.set_wm_class("changed", "Changed")
        connection.sync()
        with pytest.raises(RuntimeError, match="changed"):
            backend.check()
    finally:
        backend.close()


def test_private_session_disconnect_releases_held_keys(game_receiver):
    connection, _, address, target = game_receiver
    backend = IsolatedBackend(address, target)
    backend.send(Step(0, "key_down", "KEY_W"))
    backend.close()
    events = received(connection)
    assert [event.type for event in events if event.type in (X.KeyPress, X.KeyRelease)] == [
        X.KeyPress,
        X.KeyRelease,
    ]


def test_private_start_coordinates_are_checked_in_game_client_space(game_receiver):
    _, _, address, target = game_receiver
    backend = IsolatedBackend(address, target)
    try:
        with pytest.raises(RuntimeError, match="outside"):
            backend.prepare_start((600, 0))
        with pytest.raises(ValueError, match="cannot be mapped"):
            backend.prepare([Step(0, "key_down", "KEY_MACRO1")])
    finally:
        backend.close()


def test_worker_refuses_host_display_and_non_gamescope_environment(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    with pytest.raises(RuntimeError, match="Refusing input"):
        validate_environment(":0")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "gamescope")
    monkeypatch.setenv("GAMESCOPE_WAYLAND_DISPLAY", "gamescope-test")
    with pytest.raises(RuntimeError):
        validate_environment(":0.0")
    monkeypatch.setenv("DISPLAY", ":987")
    validate_environment(":0")


def test_sober_profile_refuses_an_existing_instance_and_keeps_shell_text_literal(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/" + value)
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="org.vinegarhq.Sober\n")
    )
    with pytest.raises(RuntimeError, match="Close your existing Sober"):
        application_command()
    assert application_command(False, 'game "literal; value"') == ["game", "literal; value"]
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=""))
    command = application_command()
    assert "--nosocket=wayland" in command and "--env=SDL_VIDEODRIVER=x11" in command


def test_session_launch_is_explicit_nested_and_has_no_global_input_fallback(monkeypatch):
    captured = []

    class Process:
        def __init__(self, *args, **kwargs):
            captured.append((args, kwargs))
            self.stdout = io.StringIO("Ready\n")
            self.code = None

        def poll(self):
            return self.code

        def terminate(self):
            self.code = 0

    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/" + value)
    monkeypatch.setattr(subprocess, "Popen", Process)
    session = GameSession()
    try:
        session.launch(["/usr/bin/example-game"])
        args, kwargs = captured[0]
        command = args[0]
        assert command[0] == "/usr/bin/gamescope"
        assert "-o" in command and "automater.isolated_worker" in command
        assert "--grab" not in command and "--force-grab-cursor" not in command
        assert kwargs["start_new_session"] and "shell" not in kwargs
        assert session.directory.stat().st_mode & 0o777 == 0o700
    finally:
        session.close()
        session.cleanup_finished()


def test_run_settings_route_only_to_the_selected_session(qtbot, tmp_path, monkeypatch):
    from test_engine import Backend
    from test_gui import clean, window

    win = window(qtbot, tmp_path, monkeypatch)
    called = []

    class PrivateBackend(Backend):
        coordinate_space = "window"

        def __init__(self, address, target):
            super().__init__()
            called.append((address, target))

    def forbidden():
        pytest.fail("Isolated playback must never fall back to desktop input")

    monkeypatch.setattr("automater.window.UInputBackend", forbidden)
    monkeypatch.setattr("automater.window.IsolatedBackend", PrivateBackend)
    win.mode.setCurrentIndex(2)
    win.test_mode.setChecked(False)
    win.countdown.setValue(0)
    win.speed.setValue(10)
    win.toggle_play()
    assert not win.busy and not called
    address = SessionAddress("/tmp/not-opened-by-test", "nonce")
    target = WindowInfo(12, "Private game", 123, ("Game", "Game"))
    win.game_session.address = address
    win.populate_targets([target])
    win.toggle_play()
    qtbot.waitUntil(lambda: not win.busy, timeout=2000)
    assert called == [(address, target)]
    clean(win)


def test_switching_to_session_mode_clears_host_window_targets(qtbot, tmp_path, monkeypatch):
    from test_gui import clean, window

    win = window(qtbot, tmp_path, monkeypatch)
    host = WindowInfo(5, "Host window", 22, ("Host", "Host"))
    monkeypatch.setattr("automater.window.x11.windows", lambda: [host])
    win.mode.setCurrentIndex(1)
    assert win.target.findData(host) >= 0
    win.mode.setCurrentIndex(2)
    assert win.target.findData(host) < 0 and win.target.currentData() is None
    clean(win)
