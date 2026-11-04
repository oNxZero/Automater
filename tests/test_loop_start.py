import time
from types import SimpleNamespace

import pytest
from test_engine import Backend
from test_gui import clean, window

from automater.engine import PlaybackOptions, Replay
from automater.models import Script, Step
from automater.pointer import HyprlandPointer, X11Pointer, desktop_pointer


class PointBackend(Backend):
    coordinate_space = "desktop"

    def __init__(self):
        super().__init__()
        self.log = []

    def prepare_start(self, point):
        if point[0] < 0:
            raise ValueError("Outside the desktop")

    def begin_cycle(self, point):
        self.log.append(("reset", tuple(point)))

    def send(self, step):
        self.log.append(("input", step.action))
        super().send(step)


def test_start_point_resets_before_every_loop():
    backend = PointBackend()
    script = Script(
        steps=[Step(0, "key_down", "KEY_A"), Step(0, "key_up", "KEY_A")],
        start={"x": 12, "y": 34, "settle_ms": 0, "space": "desktop"},
    )
    replay = Replay(lambda: backend)
    replay.start(script, PlaybackOptions(repeats=3, countdown=0, loop_gap=0))
    assert replay.join(1)
    assert backend.log == [("reset", (12, 34)), ("input", "key_down"), ("input", "key_up")] * 3


def test_start_failure_emits_no_keys_and_closes_backend():
    backend, messages = PointBackend(), []
    replay = Replay(lambda: backend, lambda *args: messages.append(args))
    replay.start(
        Script(steps=[Step(0, "key_down", "KEY_A")]),
        PlaybackOptions(countdown=0, start_position=(-1, 10)),
    )
    assert replay.join(1)
    assert backend.log == [] and backend.closed
    assert any(k == "error" and "Outside" in value for k, value in messages)


def test_starting_coordinate_spaces_cannot_be_mixed():
    backend, messages = PointBackend(), []
    backend.coordinate_space = "window"
    replay = Replay(lambda: backend, lambda *args: messages.append(args))
    replay.start(
        Script(steps=[Step(0)], start={"x": 10, "y": 20, "settle_ms": 0, "space": "desktop"}),
        PlaybackOptions(countdown=0),
    )
    assert replay.join(1)
    assert not backend.log
    assert any(k == "error" and "different coordinate space" in v for k, v in messages)


def test_random_delay_resampled_each_loop_and_speed_applied():
    class Random:
        def __init__(self):
            self.calls = []

        def uniform(self, low, high):
            self.calls.append((low, high))
            return high

    rng, backend, messages = Random(), Backend(), []
    steps = [Step(100, "wait", delay_max_ms=200), Step(100, enabled=False, delay_max_ms=200)]
    replay = Replay(lambda: backend, lambda *args: messages.append(args), rng=rng)
    replay.start(Script(steps=steps), PlaybackOptions(speed=10, repeats=3, countdown=0, loop_gap=0))
    assert replay.join(1)
    assert rng.calls == [(100, 200)] * 3
    assert all(v[2] == pytest.approx(0.02) for k, v in messages if k == "waiting")
    assert steps[0].delay_ms == 100


def test_stop_interrupts_randomized_hold_and_releases_key():
    backend = Backend()
    replay = Replay(lambda: backend)
    replay.start(
        Script(
            steps=[
                Step(0, "key_down", "KEY_W"),
                Step(100_000, "key_up", "KEY_W", delay_max_ms=200_000),
            ]
        ),
        PlaybackOptions(countdown=0),
    )
    assert backend.sent.wait(1)
    replay.stop()
    assert replay.join(0.5)
    assert backend.events[-1] == Step(0, "key_up", "KEY_W")


def test_wayland_does_not_silently_use_xwayland_warp(monkeypatch):
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("DISPLAY", ":0")
    with pytest.raises(RuntimeError, match="X11 or Hyprland"):
        desktop_pointer()


def test_hyprland_negative_coordinates_scaling_and_verified_move(monkeypatch):
    pointer = HyprlandPointer()
    calls = []

    def command(*args, as_json=True):
        calls.append(args)
        if args[0] == "monitors":
            return [{"x": -1000, "y": 0, "width": 2000, "height": 1000, "scale": 2}]
        if args[0] == "cursorpos":
            return {"x": -500, "y": 250}
        return "ok"

    monkeypatch.setattr(pointer, "command", command)
    pointer.move((-500, 250))
    assert ("dispatch", "movecursor", "-500", "250") in calls
    with pytest.raises(ValueError):
        pointer.validate((100, 250))


def test_x11_pointer_bounds_and_move_verification(monkeypatch):
    class Root:
        point = (0, 0)
        reject = False

        def get_geometry(self):
            return SimpleNamespace(width=1920, height=1080)

        def query_pointer(self):
            return SimpleNamespace(root_x=self.point[0], root_y=self.point[1])

        def warp_pointer(self, x, y):
            if not self.reject:
                self.point = (x, y)

    root = Root()
    connection = SimpleNamespace(
        screen=lambda: SimpleNamespace(root=root), sync=lambda: None, close=lambda: None
    )
    monkeypatch.setattr("Xlib.display.Display", lambda: connection)
    pointer = X11Pointer()
    pointer.move((120, 340))
    assert pointer.position() == (120, 340)
    with pytest.raises(ValueError):
        pointer.validate((1920, 0))
    root.reject = True
    with pytest.raises(RuntimeError, match="did not accept"):
        pointer.move((10, 20))
    pointer.close()


def test_preview_with_position_never_touches_desktop(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)

    def forbidden():
        raise AssertionError("Preview must not touch desktop")

    monkeypatch.setattr("automater.pointer.desktop_pointer", forbidden)
    win.start_enabled.setChecked(True)
    win.start_x.setValue(300)
    win.start_y.setValue(200)
    win.start_settle.setValue(0)
    win.countdown.setValue(0)
    win.speed.setValue(10)
    win.toggle_play()
    qtbot.waitUntil(lambda: not win.busy, timeout=2000)
    assert not win.playback_error
    clean(win)


def test_position_capture_and_cancelled_callback(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    closed = []
    provider = SimpleNamespace(position=lambda: (320, 240), close=lambda: closed.append(True))
    monkeypatch.setattr("automater.pointer.desktop_pointer", lambda: provider)
    win.start_enabled.setChecked(True)
    win.pick_position()
    win.pick_deadline = time.monotonic() - 0.01
    win.update_countdown()
    qtbot.waitUntil(lambda: not win.busy, timeout=1000)
    assert (win.start_x.value(), win.start_y.value()) == (320, 240)
    assert closed == [True]
    win.pick_position()
    old = win.pick_generation
    win.stop()
    win.position_picked(old, (999, 999), "")
    assert win.start_x.value() == 320 and not win.busy
    clean(win)
