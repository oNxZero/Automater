from evdev import InputEvent, ecodes
from PySide6.QtCore import Qt
from test_gui import clean, window

from automater.linux_input import DeviceInfo
from automater.window import MainWindow


class Monitor:
    instances = []

    def __init__(self, paths, recorder, hotkey, error):
        self.paths = paths
        self.instances.append(self)

    def start(self):
        pass

    def stop(self):
        return True


KEYBOARD = DeviceInfo("event1", "Keyboard", True, "keyboard-stable", keyboard=True)
MOUSE = DeviceInfo("event2", "Mouse", True, "mouse-stable", mouse=True)


def test_device_selection_is_applied_and_survives_renumbering(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    monkeypatch.setattr("automater.window.DeviceMonitor", Monitor)
    monkeypatch.setattr("automater.window.devices", lambda: [KEYBOARD, MOUSE])
    win.refresh_devices()
    assert win.monitor_ok and win.monitor.paths == ["event1", "event2"]
    win.device_list.item(1).setCheckState(Qt.Unchecked)
    win.refresh_devices()
    assert win.monitor.paths == ["event1"]
    assert win.preferences.device_ids == ["keyboard-stable"]
    monkeypatch.setattr(
        "automater.window.devices",
        lambda: [DeviceInfo("event9", "Keyboard", True, "keyboard-stable", keyboard=True), MOUSE],
    )
    win.refresh_devices()
    assert win.monitor.paths == ["event9"]
    win.recommend_devices()
    assert win.monitor.paths == ["event9", "event2"]
    clean(win)


def test_permission_repair_makes_device_selectable(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    monkeypatch.setattr("automater.window.DeviceMonitor", Monitor)
    monkeypatch.setattr(
        "automater.window.devices",
        lambda: [DeviceInfo("event1", "Keyboard", False, issue="Permission needed")],
    )
    win.refresh_devices()
    assert not win.device_list.item(0).flags() & Qt.ItemIsEnabled
    assert win.preferences.device_ids is None
    monkeypatch.setattr("automater.window.devices", lambda: [KEYBOARD])
    win.refresh_devices()
    assert win.device_list.item(0).checkState() == Qt.Checked
    assert win.monitor_ok
    clean(win)


def test_monitor_failure_never_claims_ready(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)

    class Failed(Monitor):
        def start(self):
            raise PermissionError("event1 denied")

    monkeypatch.setattr("automater.window.DeviceMonitor", Failed)
    monkeypatch.setattr("automater.window.devices", lambda: [KEYBOARD])
    win.refresh_devices()
    assert not win.monitor_ok
    assert "Could not connect" in win.notice.text()
    assert "event1 denied" in win.device_details.toPlainText()
    assert "denied" not in win.status.text()
    clean(win)


def test_stale_monitor_messages_cannot_stop_new_listener(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    monkeypatch.setattr("automater.window.DeviceMonitor", Monitor)
    monkeypatch.setattr("automater.window.devices", lambda: [KEYBOARD])
    win.refresh_devices()
    old = win.monitor_generation
    win.refresh_devices()
    win.route_monitor_error(old, "old listener closed")
    win.route_hotkey(old, "record")
    assert win.monitor_ok and not win.busy
    clean(win)


def test_run_and_capture_settings_restore_on_restart(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.speed.setValue(1.7)
    win.repeats.setValue(4)
    win.countdown.setValue(5)
    win.capture_motion.setChecked(False)
    win.append_recording.setChecked(True)
    clean(win)
    win.close()
    other = MainWindow(config_dir=tmp_path, demo=True)
    qtbot.addWidget(other)
    assert other.speed.value() == 1.7 and other.repeats.value() == 4
    assert other.countdown.value() == 5
    assert not other.capture_motion.isChecked()
    assert other.append_recording.isChecked()
    clean(other)


def test_append_recording_and_undo_keep_existing_work(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    before = list(win.model.steps)
    monkeypatch.setattr(win, "refresh_devices", lambda: None)
    win.monitor_ok = True
    win.countdown.setValue(0)
    win.append_recording.setChecked(True)
    win.toggle_record()
    win.recorder.feed(InputEvent(0, 0, ecodes.EV_KEY, ecodes.KEY_A, 1))
    win.stop()
    assert win.model.steps[: len(before)] == before
    assert win.model.steps[len(before)].code == "KEY_A"
    win.undo.undo()
    assert win.model.steps == before
    clean(win)


def test_idle_workspace_has_no_sidebar_or_persistent_properties(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    assert not win.inspector_panel.isVisible()
    assert not win.pause_btn.isVisible() and not win.stop_btn.isVisible()
    assert not win.notice.isVisible()
    win.show_inspector(1)
    assert win.inspector_panel.isVisible()
    win.hide_inspector()
    assert not win.inspector_panel.isVisible()
    clean(win)
