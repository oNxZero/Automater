from evdev import InputEvent, ecodes

from moonlight_studio.linux_input import Recorder


def event(code, value, kind=ecodes.EV_KEY):
    return InputEvent(0, 0, kind, code, value)


def test_only_records_while_active_and_excludes_controls():
    recorder = Recorder()
    recorder.feed(event(ecodes.KEY_A, 1))
    assert recorder.steps == []
    recorder.start()
    for code in (ecodes.KEY_F6, ecodes.KEY_F7, ecodes.KEY_F8, ecodes.KEY_F12):
        recorder.feed(event(code, 1))
        recorder.feed(event(code, 0))
    recorder.feed(event(ecodes.KEY_A, 1))
    recorder.feed(event(ecodes.KEY_A, 2))
    recorder.feed(event(ecodes.KEY_A, 1))
    steps = recorder.stop()
    assert [s.action for s in steps] == ["key_down", "wait", "key_up"]
    assert steps[-1].code == "KEY_A"
    recorder.feed(event(ecodes.KEY_B, 1))
    assert recorder.steps == steps


def test_filters_and_mouse_axes():
    recorder = Recorder()
    recorder.start(keyboard=False, mouse=True, motion=False)
    recorder.feed(event(ecodes.KEY_A, 1))
    recorder.feed(event(ecodes.REL_X, 8, ecodes.EV_REL))
    recorder.feed(event(ecodes.BTN_LEFT, 1))
    recorder.feed(event(ecodes.BTN_LEFT, 0))
    recorder.feed(event(ecodes.REL_WHEEL, -1, ecodes.EV_REL))
    steps = recorder.stop()
    assert [s.action for s in steps] == ["key_down", "key_up", "scroll", "wait"]
    assert steps[2].y == -1


def test_release_without_press_ignored_and_relative_motion_preserved():
    recorder = Recorder()
    recorder.start()
    recorder.feed(event(ecodes.KEY_A, 0))
    recorder.feed(event(ecodes.REL_X, -15, ecodes.EV_REL))
    recorder.feed(event(ecodes.REL_Y, 9, ecodes.EV_REL))
    steps = recorder.stop()
    assert (steps[0].x, steps[0].y) == (-15, 9)
    assert [step.action for step in steps] == ["move", "wait"]


def test_two_devices_share_one_logical_key_hold():
    recorder = Recorder()
    recorder.start()
    recorder.feed(event(ecodes.KEY_A, 1), source="keyboard1")
    recorder.feed(event(ecodes.KEY_A, 1), source="keyboard2")
    recorder.feed(event(ecodes.KEY_A, 0), source="keyboard1")
    assert recorder.count() == 1
    recorder.feed(event(ecodes.KEY_A, 0), source="keyboard2")
    assert [s.action for s in recorder.stop()] == ["key_down", "key_up", "wait"]


def test_kernel_timestamps_preserve_batch_spacing():
    recorder = Recorder()
    recorder.start()
    start = recorder._last
    recorder.feed(event(ecodes.KEY_A, 1), occurred_at=start + 0.125)
    recorder.feed(event(ecodes.KEY_A, 0), occurred_at=start + 0.375)
    steps = recorder.stop()
    assert round(steps[0].delay_ms) == 125
    assert round(steps[1].delay_ms) == 250


def test_monitor_routes_physical_events_and_hotkeys(monkeypatch):
    import time

    from moonlight_studio import linux_input

    recorder = Recorder()
    recorder.start()
    codes = [(ecodes.KEY_A, 1), (ecodes.KEY_A, 0), (ecodes.KEY_F12, 1)]
    stamp = time.time() + 0.01
    events = [InputEvent(int(stamp), int(stamp % 1 * 1e6), ecodes.EV_KEY, c, v) for c, v in codes]

    class Device:
        name = "Test keyboard"
        path = "test"

        def __init__(self, path):
            pass

        def read(self):
            return events

        def close(self):
            pass

    errors, shortcuts = [], []
    monitor = linux_input.DeviceMonitor(["test"], recorder, shortcuts.append, errors.append)

    def hotkey(action):
        shortcuts.append(action)
        monitor._stop.set()

    monitor.hotkey = hotkey
    monkeypatch.setattr(linux_input, "InputDevice", Device)
    monkeypatch.setattr(linux_input.select, "select", lambda *args: (args[0], [], []))
    monitor._run()
    assert not errors
    assert shortcuts == ["stop"]
    assert [s.action for s in recorder.stop()] == ["key_down", "key_up", "wait"]


def test_armed_recording_uses_deadline_without_waiting_for_gui(monkeypatch):
    import pytest

    from moonlight_studio import linux_input

    monkeypatch.setattr(linux_input.time, "monotonic", lambda: 102.0)
    recorder = Recorder()
    recorder.start(start_at=101.0)
    recorder.feed(event(ecodes.KEY_B, 1), occurred_at=100.99)
    recorder.feed(event(ecodes.KEY_A, 1), occurred_at=101.01)
    recorder.feed(event(ecodes.KEY_A, 0), occurred_at=101.06)
    steps = recorder.stop()
    assert [s.code for s in steps[:2]] == ["KEY_A", "KEY_A"]
    assert steps[0].delay_ms == pytest.approx(10)
    assert steps[1].delay_ms == pytest.approx(50)


def test_monitor_interleaves_ready_keyboard_and_mouse_batches_by_kernel_timestamp(monkeypatch):
    from moonlight_studio import linux_input

    recorder = Recorder()
    recorder.start(start_at=100)

    class Device:
        def __init__(self, path, fd, events):
            self.path, self.fd, self.events = path, fd, events

        def read(self):
            return self.events

        def close(self):
            pass

    keyboard = Device(
        "keyboard",
        1,
        [
            InputEvent(100, 20000, ecodes.EV_KEY, ecodes.KEY_A, 1),
            InputEvent(100, 40000, ecodes.EV_KEY, ecodes.KEY_A, 0),
            InputEvent(100, 50000, ecodes.EV_KEY, ecodes.KEY_F12, 1),
        ],
    )
    mouse = Device(
        "mouse",
        2,
        [
            InputEvent(100, 10000, ecodes.EV_REL, ecodes.REL_X, 12),
            InputEvent(100, 10000, ecodes.EV_SYN, ecodes.SYN_REPORT, 0),
            InputEvent(100, 30000, ecodes.EV_REL, ecodes.REL_Y, 9),
            InputEvent(100, 30000, ecodes.EV_SYN, ecodes.SYN_REPORT, 0),
        ],
    )
    errors = []
    monitor = linux_input.DeviceMonitor([], recorder, lambda _: monitor._stop.set(), errors.append)
    monitor._monotonic_fds = {1, 2}
    monkeypatch.setattr(linux_input.select, "select", lambda *args: ([keyboard, mouse], [], []))
    monitor._run([keyboard, mouse])
    steps = recorder.stop()
    assert not errors
    assert [s.action for s in steps] == ["move", "key_down", "move", "key_up", "wait"]
    assert [round(s.delay_ms) for s in steps[:4]] == [10, 10, 10, 10]


def test_monitor_drains_full_evdev_batches_before_merging_newer_key_events(monkeypatch):
    from moonlight_studio import linux_input

    recorder = Recorder()
    recorder.start(start_at=100)
    packets = []
    for index in range(1, 40):
        packets.extend(
            [
                InputEvent(100, index * 1000, ecodes.EV_REL, ecodes.REL_X, 1),
                InputEvent(100, index * 1000, ecodes.EV_SYN, ecodes.SYN_REPORT, 0),
            ]
        )

    class Device:
        def __init__(self, path, fd, batches):
            self.path, self.fd, self.batches = path, fd, iter(batches)

        def read(self):
            return next(self.batches)

        def close(self):
            pass

    mouse = Device("mouse", 2, [packets[:64], packets[64:]])
    keyboard = Device(
        "keyboard",
        1,
        [
            [
                InputEvent(100, 20000, ecodes.EV_KEY, ecodes.KEY_A, 1),
                InputEvent(100, 40000, ecodes.EV_KEY, ecodes.KEY_A, 0),
                InputEvent(100, 50000, ecodes.EV_KEY, ecodes.KEY_F12, 1),
            ]
        ],
    )
    errors = []
    monitor = linux_input.DeviceMonitor([], recorder, lambda _: monitor._stop.set(), errors.append)
    monitor._monotonic_fds = {1, 2}
    monkeypatch.setattr(linux_input.select, "select", lambda *args: ([keyboard, mouse], [], []))
    monitor._run([keyboard, mouse])
    steps = recorder.stop()
    assert not errors
    assert sum(s.x for s in steps if s.action == "move") == 39
    assert round(sum(s.delay_ms for s in steps[:-1])) == 40
    assert round(steps[-2].delay_ms) == 1
