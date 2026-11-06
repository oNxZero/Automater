"""All XTEST events go to a new, test-owned Xvfb server, never the host display."""

import io
import os
import select
import shutil
import subprocess
import tempfile
import threading
import time
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest
from evdev import InputEvent, ecodes
from Xlib import X, display

from automater import storage
from automater.engine import PlaybackOptions, Replay
from automater.isolated import (
    GameSession,
    IsolatedBackend,
    SessionAddress,
    SessionRPC,
    application_command,
)
from automater.isolated_worker import InputHandler, InputServer, validate_environment
from automater.linux_input import Recorder
from automater.models import Script, Step
from automater.open_windows import GuardedDesktopBackend
from automater.x11 import BackgroundBackend, FocusGuard, WindowInfo, identity


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


def wait_for_input(connection, count):
    events = []
    deadline = time.monotonic() + 2
    while len(events) < count and time.monotonic() < deadline:
        events.extend(received(connection))
        time.sleep(0.005)
    assert len(events) == count, [(event.type, event.detail) for event in events]
    return events


@pytest.mark.parametrize("destination", ["isolated", "background"])
@pytest.mark.parametrize("pause_resume", [False, True])
def test_replay_stop_and_pause_release_real_held_input(
    game_receiver, owned_display, monkeypatch, destination, pause_resume
):
    connection, window, address, target = game_receiver
    window.warp_pointer(100, 100)
    connection.sync()
    received(connection)
    if destination == "isolated":
        factory = partial(IsolatedBackend, address, target)
    else:
        monkeypatch.setenv("DISPLAY", owned_display)
        factory = partial(BackgroundBackend, target)
    script = Script(
        steps=[
            Step(0, "key_down", "KEY_LEFTSHIFT"),
            Step(0, "key_down", "KEY_W"),
            Step(0, "key_down", "BTN_LEFT"),
            Step(3_600_000),
        ]
    )
    replay = Replay(factory)
    replay.start(script, PlaybackOptions(countdown=0))
    try:
        presses = wait_for_input(connection, 3)
        assert [event.type for event in presses] == [X.KeyPress, X.KeyPress, X.ButtonPress]
        if pause_resume:
            replay.pause()
            releases = wait_for_input(connection, 3)
            assert [event.type for event in releases] == [
                X.ButtonRelease,
                X.KeyRelease,
                X.KeyRelease,
            ]
            replay.pause()
            restored = wait_for_input(connection, 3)
            assert [(event.type, event.detail) for event in restored] == [
                (X.KeyPress, ecodes.KEY_LEFTSHIFT + 8),
                (X.ButtonPress, 1),
                (X.KeyPress, ecodes.KEY_W + 8),
            ]
            assert restored[-1].state & X.ShiftMask
            assert restored[-1].state & X.Button1Mask
        replay.stop()
        assert replay.join(1), "Stop did not interrupt the hour-long timer"
        assert replay.timeline["outcome"] == "stopped", replay.timeline
        releases = wait_for_input(connection, 3)
        assert [(event.type, event.detail) for event in releases] == [
            (X.ButtonRelease, 1),
            (X.KeyRelease, ecodes.KEY_W + 8),
            (X.KeyRelease, ecodes.KEY_LEFTSHIFT + 8),
        ]
    finally:
        replay.stop()
        assert replay.join()


def test_real_focus_change_stops_replay_and_still_delivers_cleanup(
    game_receiver, owned_display, monkeypatch
):
    connection, window, _, target = game_receiver
    monkeypatch.setenv("DISPLAY", owned_display)
    window.set_input_focus(X.RevertToParent, X.CurrentTime)
    connection.sync()

    def factory():
        guard = FocusGuard(target)
        return GuardedDesktopBackend(BackgroundBackend(target), guard.check, guard.close)

    replay = Replay(factory)
    replay.start(
        Script(steps=[Step(0, "key_down", "KEY_W"), Step(3_600_000)]),
        PlaybackOptions(countdown=0),
    )
    try:
        assert wait_for_input(connection, 1)[0].type == X.KeyPress
        connection.screen().root.set_input_focus(X.RevertToParent, X.CurrentTime)
        connection.sync()
        assert replay.join(1), "Focus loss did not interrupt playback"
        assert replay.timeline["outcome"] == "failed"
        assert "lost focus" in replay.timeline["error"]
        release = wait_for_input(connection, 1)[0]
        assert (release.type, release.detail) == (X.KeyRelease, ecodes.KEY_W + 8)
        assert release.window.id == window.id
    finally:
        replay.stop()
        assert replay.join()


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


@pytest.mark.parametrize("destination", ["isolated", "background"])
def test_record_save_load_and_repeat_delivers_input_to_a_private_window(
    game_receiver, owned_display, tmp_path, monkeypatch, destination
):
    connection, _, address, target = game_receiver
    recorder = Recorder()
    started = time.monotonic() - 0.1
    recorder.start(start_at=started)
    reports = [
        (ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 1),
        (ecodes.EV_KEY, ecodes.KEY_W, 1),
        (ecodes.EV_REL, ecodes.REL_X, 12),
        (ecodes.EV_REL, ecodes.REL_Y, -8),
        (ecodes.EV_SYN, ecodes.SYN_REPORT, 0),
        (ecodes.EV_REL, ecodes.REL_WHEEL, -2),
        (ecodes.EV_REL, ecodes.REL_HWHEEL, 1),
        (ecodes.EV_SYN, ecodes.SYN_REPORT, 0),
        (ecodes.EV_KEY, ecodes.BTN_LEFT, 1),
        (ecodes.EV_KEY, ecodes.BTN_LEFT, 0),
        (ecodes.EV_KEY, ecodes.KEY_W, 0),
        (ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 0),
    ]
    for index, report in enumerate(reports):
        recorder.feed(InputEvent(0, 0, *report), occurred_at=started + index / 1000)
    path = tmp_path / "recorded.json"
    script = Script(
        "Recorded route",
        steps=recorder.stop(),
        start={"x": 100, "y": 120, "settle_ms": 0, "space": "window"},
    )
    storage.save(script, path)
    loaded = storage.load(path)
    assert loaded.steps == script.steps
    assert [(s.x, s.y) for s in loaded.steps if s.action == "move"] == [(12, -8)]
    assert [(s.x, s.y) for s in loaded.steps if s.action == "scroll"] == [(1, -2)]
    if destination == "isolated":
        factory = partial(IsolatedBackend, address, target)
    else:
        monkeypatch.setenv("DISPLAY", owned_display)
        factory = partial(BackgroundBackend, target)
    replay = Replay(factory)
    replay.start(loaded, PlaybackOptions(countdown=0, repeats=3, speed=10, loop_gap=0))
    try:
        assert replay.join(3)
        assert replay.timeline["outcome"] == "finished", replay.timeline
        events = received(connection)
        cycle = [
            X.MotionNotify,
            X.KeyPress,
            X.KeyPress,
            X.MotionNotify,
            X.ButtonPress,
            X.ButtonRelease,
            X.ButtonPress,
            X.ButtonRelease,
            X.ButtonPress,
            X.ButtonRelease,
            X.ButtonPress,
            X.ButtonRelease,
            X.KeyRelease,
            X.KeyRelease,
        ]
        assert [event.type for event in events] == cycle * 3
        assert all(event.send_event == (destination == "background") for event in events)
        for offset in range(0, len(events), len(cycle)):
            assert (events[offset].event_x, events[offset].event_y) == (100, 120)
            assert (events[offset + 3].event_x, events[offset + 3].event_y) == (112, 112)
            assert [events[offset + i].detail for i in (1, 2, 12, 13)] == [
                ecodes.KEY_LEFTSHIFT + 8,
                ecodes.KEY_W + 8,
                ecodes.KEY_W + 8,
                ecodes.KEY_LEFTSHIFT + 8,
            ]
            assert [events[offset + i].detail for i in (4, 6, 8, 10)] == [5, 5, 7, 1]
            assert events[offset + 2].state & X.ShiftMask
            assert events[offset + 11].state & X.Button1Mask
    finally:
        replay.stop()
        assert replay.join()


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
