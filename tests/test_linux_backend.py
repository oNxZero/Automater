from evdev import InputEvent, ecodes

from moonlight_studio import linux_input
from moonlight_studio.models import Step


def test_uinput_translation_and_close(monkeypatch):
    class Output:
        def __init__(self, caps, name):
            self.caps, self.name, self.events = caps, name, []
            self.closed = False

        def write(self, *event):
            self.events.append(event)

        def syn(self):
            self.events.append((ecodes.EV_SYN, ecodes.SYN_REPORT, 0))

        def close(self):
            self.closed = True

    monkeypatch.setattr(linux_input.os, "access", lambda *args: True)
    monkeypatch.setattr(linux_input, "UInput", Output)
    backend = linux_input.UInputBackend()
    for step in [
        Step(0, "key_down", "KEY_W"),
        Step(0, "key_up", "KEY_W"),
        Step(0, "move", x=12, y=-8),
        Step(0, "scroll", x=1, y=-2),
    ]:
        backend.send(step)
    assert backend.device.name == linux_input.VIRTUAL_NAME
    assert backend.device.events == [
        (1, ecodes.KEY_W, 1),
        (0, 0, 0),
        (1, ecodes.KEY_W, 0),
        (0, 0, 0),
        (2, ecodes.REL_X, 12),
        (2, ecodes.REL_Y, -8),
        (0, 0, 0),
        (2, ecodes.REL_HWHEEL, 1),
        (2, ecodes.REL_WHEEL, -2),
        (0, 0, 0),
    ]
    backend.close()
    assert backend.device.closed


def test_monitor_excludes_virtual_devices(monkeypatch):
    opened, closed, errors = [], [], []

    class Virtual:
        name = linux_input.VIRTUAL_NAME

        def __init__(self, path):
            opened.append(path)

        def close(self):
            closed.append(True)

    monkeypatch.setattr(linux_input, "InputDevice", Virtual)
    monitor = linux_input.DeviceMonitor(
        ["virtual"], linux_input.Recorder(), lambda _: None, errors.append
    )
    monitor._run()
    assert opened == ["virtual"] and closed == [True]
    assert "No readable" in errors[0]


def test_dropped_events_report_error_and_close_device(monkeypatch):
    closed, errors = [], []

    class Physical:
        name = "Keyboard"

        def __init__(self, path):
            pass

        def read(self):
            return [InputEvent(0, 0, ecodes.EV_SYN, ecodes.SYN_DROPPED, 0)]

        def close(self):
            closed.append(True)

    monkeypatch.setattr(linux_input, "InputDevice", Physical)
    monkeypatch.setattr(linux_input.select, "select", lambda *args: (args[0], [], []))
    monitor = linux_input.DeviceMonitor(
        ["physical"], linux_input.Recorder(), lambda _: None, errors.append
    )
    monitor._run()
    assert "dropped" in errors[0]
    assert closed == [True]
