from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from moonlight_studio import storage
from moonlight_studio.models import Step
from moonlight_studio.window import MainWindow


def window(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Discard)
    monkeypatch.setattr("moonlight_studio.window.devices", lambda: [])
    monkeypatch.setattr("moonlight_studio.window.x11.windows", lambda: [])
    win = MainWindow(config_dir=tmp_path, demo=True)
    qtbot.addWidget(win)
    win.show()
    return win


def clean(win):
    win.saved_snapshot = win.script().to_dict()


def test_editor_undo_redo_and_validation(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    original = list(win.model.steps)
    win.add_step()
    assert len(win.model.steps) == len(original) + 2
    win.undo.undo()
    assert win.model.steps == original
    win.undo.redo()
    assert len(win.model.steps) == len(original) + 2
    assert not win.model.setData(win.model.index(0, 1), -1)
    assert "between" in win.status.text()
    win.model.setData(win.model.index(0, 0), Qt.Unchecked, Qt.CheckStateRole)
    assert not win.model.steps[0].enabled
    clean(win)


def test_test_mode_playback_and_busy_controls(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.countdown.setValue(0)
    win.speed.setValue(10)
    win.toggle_play()
    assert win.busy
    assert not win.table.isEnabled()
    qtbot.waitUntil(lambda: not win.busy, timeout=3000)
    assert "finished" in win.status.text()
    assert win.table.isEnabled()
    assert win.model.playing_row == -1
    clean(win)


def test_autosave_open_and_atomic_file(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.name.setText("Changed")
    win.autosave()
    assert storage.load(win.recovery_path).name == "Changed"
    path = tmp_path / "scripts" / "saved.json"
    win.path = path
    assert win.save_script()
    assert not win.dirty()
    assert win.library.count() == 1
    win.load_script(storage.load(path), path)
    assert win.name.text() == "Changed"


def test_record_requires_device_access(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.toggle_record()
    assert not win.busy
    assert "No selected readable" in win.status.text()
    assert win.pages.currentIndex() == 2
    clean(win)


def test_stop_cancels_record_countdown_without_overwriting(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    before = list(win.model.steps)
    win.record_pending = True
    win.update_busy(True)
    win.stop()
    assert not win.busy
    assert win.model.steps == before
    clean(win)


def test_background_requires_explicit_target(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.test_mode.setChecked(False)
    win.mode.setCurrentIndex(1)
    win.toggle_play()
    assert not win.busy
    assert "Choose a target" in win.status.text()
    clean(win)


def test_new_script_preserves_unsaved_work_in_another_tab(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.model.commit([Step(42)], "Edit")
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Cancel)
    win.new_script()
    assert win.model.steps == [] and win.document_tabs.count() == 2
    win.document_tabs.setCurrentIndex(0)
    assert win.model.steps == [Step(42)]
    clean(win)


def test_record_stop_handoff_can_be_undone(qtbot, tmp_path, monkeypatch):
    from evdev import InputEvent, ecodes

    win = window(qtbot, tmp_path, monkeypatch)
    before = list(win.model.steps)
    monkeypatch.setattr(win, "refresh_devices", lambda: None)
    win.monitor_ok = True
    win.countdown.setValue(0)
    win.toggle_record()
    assert win.busy and win.recorder.active
    win.recorder.feed(InputEvent(0, 0, ecodes.EV_KEY, ecodes.KEY_A, 1))
    win.stop()
    assert not win.busy
    assert win.model.steps[: len(before)] == before
    assert [s.action for s in win.model.steps[len(before) :]] == ["key_down", "wait", "key_up"]
    assert storage.load(win.recovery_path).steps == win.model.steps
    win.undo.undo()
    assert win.model.steps == before
    clean(win)


def test_recovery_is_unsaved_and_requires_save(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.name.setText("Recovered route")
    win.autosave()
    win.load_script(win.script())
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    win.offer_recovery()
    assert win.name.text() == "Recovered route"
    assert win.dirty()
    clean(win)
