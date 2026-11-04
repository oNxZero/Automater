from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
from test_gui import clean, window

from moonlight_studio.models import Script, Step
from moonlight_studio.storage import load, save


def test_tabs_preserve_independent_edits_undo_and_run_settings(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    original = list(win.model.steps)
    win.name.setText("First")
    win.add_step(2)
    first = list(win.model.steps)
    win.speed.setValue(2)
    win.workflow.follow_btn.setChecked(False)
    win.new_script()
    win.name.setText("Second")
    win.add_step(2)
    second = list(win.model.steps)
    win.speed.setValue(3)
    win.workflow.follow_btn.setChecked(True)
    assert win.document_tabs.count() == 2
    win.document_tabs.setCurrentIndex(0)
    assert win.name.text() == "First" and win.model.steps == first and win.speed.value() == 2
    assert not win.workflow.follow_btn.isChecked()
    win.undo.undo()
    assert win.model.steps == original
    win.document_tabs.setCurrentIndex(1)
    assert win.name.text() == "Second" and win.model.steps == second and win.speed.value() == 3
    assert win.workflow.follow_btn.isChecked()
    win.undo.undo()
    assert win.model.steps == []
    win.undo.redo()
    assert win.model.steps == second
    clean(win)


def test_close_cancel_and_last_tab_leave_a_usable_document(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.add_step(2)
    monkeypatch.setattr("moonlight_studio.dialogs.SaveChangesDialog.ask", lambda *args: "cancel")
    win.close_document(0)
    assert win.document_tabs.count() == 1 and win.dirty()
    monkeypatch.setattr("moonlight_studio.dialogs.SaveChangesDialog.ask", lambda *args: "discard")
    win.close_document(0)
    assert win.document_tabs.count() == 1 and not win.model.steps and not win.dirty()
    clean(win)


def test_open_file_activates_existing_tab_without_overwriting_edits(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    path = tmp_path / "example.json"
    save(Script("File", steps=[Step(50)]), path)
    win.open_path(path)
    win.add_step(2)
    edited = list(win.model.steps)
    win.new_script()
    count = win.document_tabs.count()
    win.open_path(path)
    assert win.document_tabs.count() == count and win.model.steps == edited
    clean(win)


def test_recovery_retains_dirty_work_from_each_tab(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.name.setText("First unsaved")
    win.add_step(2)
    first = list(win.model.steps)
    win.new_script()
    win.name.setText("Second unsaved")
    win.add_step(2)
    second = list(win.model.steps)
    win.autosave()
    recovered = [load(path) for path in tmp_path.glob("recovery-*.json")]
    assert {s.name for s in recovered} == {"First unsaved", "Second unsaved"}
    other = window(qtbot, tmp_path, monkeypatch)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    other.offer_recovery()
    docs = {doc.script.name: doc for doc in other.documents.values()}
    assert docs["First unsaved"].script.steps == first
    assert docs["Second unsaved"].script.steps == second
    assert other.dirty()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Discard)
    clean(win)
    clean(other)


def test_tab_shortcuts_and_close_cannot_switch_during_playback(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.activateWindow()
    qtbot.wait(20)
    qtbot.keyClick(win, Qt.Key_T, Qt.ControlModifier)
    assert win.document_tabs.count() == 2
    win.model.commit([Step(5000)], "Long timer")
    win.test_mode.setChecked(True)
    win.countdown.setValue(0)
    win.toggle_play()
    assert not win.document_tabs.isEnabled()
    win.close_document(1)
    assert win.document_tabs.count() == 2
    win.stop()
    qtbot.waitUntil(lambda: not win.busy, timeout=1500)
    assert win.document_tabs.isEnabled()
    clean(win)


def test_save_as_cannot_overwrite_file_open_in_another_tab(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    path = tmp_path / "one.json"
    save(Script("File", steps=[Step(25)]), path)
    win.open_path(path)
    win.new_script()
    win.path = path
    win.add_step(2)
    assert not win.save_script()
    assert load(path).steps == [Step(25)]
    assert "another workflow tab" in win.status.text()
    win.path = None
    clean(win)
