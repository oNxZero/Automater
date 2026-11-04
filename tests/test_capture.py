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
    assert (steps[0].x, steps[0].y) == (-15, 0)
    assert (steps[1].x, steps[1].y) == (0, 9)


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
