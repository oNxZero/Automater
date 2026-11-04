"""Uses an unmapped receiver; never focuses a window or emits desktop input."""

import pytest
from Xlib import X, display

from automater.models import Step
from automater.x11 import BackgroundBackend, WindowInfo


@pytest.fixture
def receiver():
    try:
        connection = display.Display()
    except Exception as exc:
        pytest.skip(f"An X11 server is required: {exc}")
    root = connection.screen().root
    window = root.create_window(
        0,
        0,
        200,
        100,
        0,
        connection.screen().root_depth,
        event_mask=X.KeyPressMask
        | X.KeyReleaseMask
        | X.ButtonPressMask
        | X.ButtonReleaseMask
        | X.PointerMotionMask,
    )
    window.set_wm_class("automater-test", "AutomaterTest")
    connection.sync()
    target = WindowInfo(window.id, "Test receiver", 0, ("automater-test", "AutomaterTest"))
    backend = BackgroundBackend(target)
    yield connection, window, backend
    backend.close()
    try:
        window.destroy()
        connection.sync()
    finally:
        connection.close()


def received(connection):
    connection.sync()
    result = []
    while connection.pending_events():
        result.append(connection.next_event())
    return result


def test_directed_key_mouse_scroll_and_no_focus_change(receiver):
    connection, window, backend = receiver
    focus = connection.get_input_focus().focus
    steps = [
        Step(0, "key_down", "KEY_LEFTSHIFT"),
        Step(0, "key_down", "KEY_A"),
        Step(0, "key_up", "KEY_A"),
        Step(0, "key_up", "KEY_LEFTSHIFT"),
        Step(0, "move", x=5, y=-2),
        Step(0, "key_down", "BTN_LEFT"),
        Step(0, "key_up", "BTN_LEFT"),
        Step(0, "scroll", y=1),
    ]
    backend.prepare(steps)
    for step in steps:
        backend.send(step)
    events = received(connection)
    assert [e.type for e in events] == [2, 2, 3, 3, 6, 4, 5, 4, 5]
    assert all(e.window.id == window.id and e.send_event for e in events)
    assert events[1].state & X.ShiftMask
    assert (events[4].event_x, events[4].event_y) == (105, 48)
    assert (events[4].root_x, events[4].root_y) == (105, 48)
    assert events[6].state & X.Button1Mask
    assert connection.get_input_focus().focus == focus


def test_two_shift_keys_keep_modifier_until_both_released(receiver):
    connection, _, backend = receiver
    for step in [
        Step(0, "key_down", "KEY_LEFTSHIFT"),
        Step(0, "key_down", "KEY_RIGHTSHIFT"),
        Step(0, "key_up", "KEY_LEFTSHIFT"),
        Step(0, "key_down", "KEY_A"),
    ]:
        backend.send(step)
    assert received(connection)[-1].state & X.ShiftMask


def test_target_identity_change_rejected(receiver):
    connection, window, backend = receiver
    window.set_wm_class("changed", "Changed")
    connection.sync()
    with pytest.raises(RuntimeError, match="identity changed"):
        backend.check()


def test_preflight_rejects_unsupported_steps(receiver):
    _, _, backend = receiver
    with pytest.raises(ValueError, match="unsupported"):
        backend.prepare([Step(0, "key_down", "BTN_TASK")])
    with pytest.raises(ValueError, match="100 notches"):
        backend.prepare([Step(0, "scroll", y=101)])


def test_background_loop_start_uses_client_coords_without_moving_pointer(receiver, monkeypatch):
    connection, window, backend = receiver
    from Xlib.ext import xtest
    from Xlib.xobject.drawable import Window

    def forbidden(*args, **kwargs):
        pytest.fail("Background routing must not move the desktop pointer")

    monkeypatch.setattr(Window, "warp_pointer", forbidden)
    monkeypatch.setattr(xtest, "fake_input", forbidden)
    backend.begin_cycle((25, 30))
    events = received(connection)
    assert events[-1].type == X.MotionNotify
    assert (events[-1].event_x, events[-1].event_y) == (25, 30)
    with pytest.raises(ValueError):
        backend.prepare_start((200, 30))
