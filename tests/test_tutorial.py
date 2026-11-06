import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QFrame, QPushButton, QScrollArea
from test_gui import clean, window

from automater.action_dialog import ActionDialog
from automater.actions import create_action
from automater.engine import DryRun
from automater.preferences import Preferences
from automater.storage import load


def start_example(qtbot, win):
    win.show_tutorial()
    guide = win.tutorial_dialog
    assert guide.step == 0
    qtbot.mouseClick(guide.card.next_btn, Qt.LeftButton)
    assert guide.step == 1
    return guide


def next_step(qtbot, guide):
    qtbot.waitUntil(lambda: guide.card.next_btn.isEnabled())
    qtbot.mouseClick(guide.card.next_btn, Qt.LeftButton)


def add_action(qtbot, win, kind, code=None, duration=100, skip=False):
    def fill_action():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, ActionDialog)
        banner = dialog.findChild(QFrame, "notice")
        assert banner is not None, "The task must stay visible inside the real Add dialog"
        if skip:
            button = next(
                button for button in banner.findChildren(QPushButton) if button.text() == "Skip"
            )
            qtbot.mouseClick(button, Qt.LeftButton)
            return
        if code:
            dialog.key.set_code(code)
        dialog.duration.setValue(duration)
        dialog.add()

    def choose_kind():
        menu = QApplication.activePopupWidget()
        assert menu is not None
        action = menu.actions()[kind]
        menu.close()
        QTimer.singleShot(0, fill_action)
        action.trigger()

    QTimer.singleShot(0, choose_kind)
    qtbot.mouseClick(win.add_btn, Qt.LeftButton)


def ready_to_run(qtbot, win):
    guide = start_example(qtbot, win)
    # This fixture isolates playback outcomes; the main test builds with real controls.
    win.insert_steps(
        create_action(0, "KEY_SPACE", duration=500)
        + create_action(2, duration=300)
        + create_action(0, "KEY_E", duration=100)
    )
    for _ in range(4):
        next_step(qtbot, guide)
    assert guide.step == 5
    return guide


def test_complete_example_builds_edits_runs_congratulates_and_starts_a_new_workflow(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    original = win.active_document_id
    before = win.script().to_dict()
    count = len(win.documents)

    class ForbiddenInput:
        startup_delay = 0.5

        def __init__(self, *args, **kwargs):
            raise AssertionError("The example must never send physical input")

    monkeypatch.setattr("automater.window.UInputBackend", ForbiddenInput)
    guide = start_example(qtbot, win)
    example = win.active_document_id
    assert example != original and len(win.documents) == count + 1
    assert win.test_mode.isChecked() and win.countdown.value() == 0
    assert not guide.card.next_btn.isEnabled()
    add_action(qtbot, win, 0, "KEY_SPACE")
    next_step(qtbot, guide)
    assert guide.step == 2
    win.action_inspector.duration.setValue(500)
    qtbot.mouseClick(win.action_inspector.apply_btn, Qt.LeftButton)
    next_step(qtbot, guide)
    assert guide.step == 3
    add_action(qtbot, win, 2, duration=300)
    next_step(qtbot, guide)
    assert guide.step == 4
    add_action(qtbot, win, 0, "KEY_E", 100)
    next_step(qtbot, guide)
    assert guide.step == 5 and not guide.succeeded
    assert [block.title for block in win.blocks] == ["Hold Space", "Timer", "Hold E"]
    win.test_mode.setChecked(False)
    win.begin_recording()
    assert not win.recorder.active and win.tutorial_dialog is guide
    qtbot.mouseClick(win.play_btn, Qt.LeftButton)
    assert win.test_mode.isChecked()
    qtbot.waitUntil(lambda: guide.succeeded, timeout=3000)
    assert guide.step == 6 and guide.card.heading.text() == "Congratulations!"
    assert win.last_run["outcome"] == "finished"
    assert win.last_run["completed_events"] == 5
    assert guide.card.progress.value() == 5
    assert guide.card.next_btn.text() == "Create my own"
    assert guide.card.keep_btn.isVisible()
    destination = tmp_path / "my-first-workflow.json"

    def save_file():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QFileDialog)
        dialog.selectFile(str(destination))
        dialog.accept()

    QTimer.singleShot(0, save_file)
    qtbot.mouseClick(win.save_btn, Qt.LeftButton)
    assert load(destination).steps == win.model.steps
    qtbot.mouseClick(guide.card.next_btn, Qt.LeftButton)
    assert win.tutorial_dialog is None
    assert win.active_document_id not in (original, example) and not win.model.steps
    assert len(win.documents[example].script.steps) == 5
    assert win.documents[example].path == destination
    assert win.documents[original].script.to_dict() == before
    assert Preferences.load(win.preferences_path).tutorial_seen
    clean(win)


def test_incorrect_example_cannot_be_clicked_through(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    guide = start_example(qtbot, win)
    add_action(qtbot, win, 0, "KEY_W")
    qtbot.wait(100)
    assert not guide.card.next_btn.isEnabled()
    guide.go(1)
    assert guide.step == 1
    win.action_inspector.key.set_code("KEY_SPACE")
    win.action_inspector.apply()
    next_step(qtbot, guide)
    assert guide.step == 2
    qtbot.wait(100)
    assert not guide.card.next_btn.isEnabled()
    win.action_inspector.duration.setValue(500)
    win.action_inspector.apply()
    next_step(qtbot, guide)
    assert guide.step == 3
    add_action(qtbot, win, 2, duration=200)
    qtbot.wait(100)
    assert not guide.card.next_btn.isEnabled()
    assert not guide.succeeded
    guide.reject()
    clean(win)


def test_a_successful_partial_run_does_not_trigger_congratulations(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    guide = start_example(qtbot, win)
    win.insert_steps(create_action(0, "KEY_SPACE", duration=100))
    qtbot.mouseClick(win.play_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: not win.busy, timeout=3000)
    qtbot.wait(100)
    assert win.last_run["outcome"] == "finished"
    assert not guide.succeeded and guide.step != 6
    guide.reject()
    clean(win)


@pytest.mark.parametrize("outcome", ["stopped", "failed"])
def test_incomplete_preview_does_not_congratulate_and_can_be_retried(
    qtbot, tmp_path, monkeypatch, outcome
):
    win = window(qtbot, tmp_path, monkeypatch)
    guide = ready_to_run(qtbot, win)
    if outcome == "failed":

        class FailingPreview(DryRun):
            def send(self, step):
                raise RuntimeError("Preview failed for this test")

        monkeypatch.setattr("automater.window.DryRun", FailingPreview)
    qtbot.mouseClick(win.play_btn, Qt.LeftButton)
    if outcome == "stopped":
        win.on_hotkey("stop")
    qtbot.waitUntil(lambda: not win.busy, timeout=3000)
    qtbot.wait(100)
    assert win.last_run["outcome"] == outcome
    assert guide.step == 5 and not guide.succeeded
    assert "retry" in guide.card.status.text() or "try again" in guide.card.status.text()
    guide.go(1)
    assert guide.step == 5
    monkeypatch.setattr("automater.window.DryRun", DryRun)
    qtbot.mouseClick(win.play_btn, Qt.LeftButton)
    qtbot.waitUntil(lambda: guide.succeeded, timeout=3000)
    qtbot.mouseClick(guide.card.keep_btn, Qt.LeftButton)
    assert win.tutorial_dialog is None and len(win.model.steps) == 5
    clean(win)


def test_first_run_skip_is_remembered_and_can_be_reopened(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    original = win.active_document_id
    count = len(win.documents)
    win.demo = False
    win.offer_tutorial()
    qtbot.mouseClick(win.tutorial_dialog.card.skip_btn, Qt.LeftButton)
    assert win.tutorial_dialog is None
    assert win.active_document_id == original and len(win.documents) == count
    win.offer_tutorial()
    assert win.tutorial_dialog is None
    win.show_tutorial()
    qtbot.keyClick(win.tutorial_dialog.card.next_btn, Qt.Key_Escape)
    assert win.tutorial_dialog is None
    other = window(qtbot, tmp_path, monkeypatch)
    other.demo = False
    other.offer_tutorial()
    assert other.tutorial_dialog is None
    clean(win)
    clean(other)


@pytest.mark.parametrize("started", [False, True])
def test_skip_keeps_user_work_and_removes_only_an_empty_example(
    qtbot, tmp_path, monkeypatch, started
):
    win = window(qtbot, tmp_path, monkeypatch)
    original = win.active_document_id
    count = len(win.documents)
    guide = start_example(qtbot, win)
    example = win.active_document_id
    if started:
        win.insert_steps(create_action(0, "KEY_SPACE", duration=100))
    qtbot.mouseClick(guide.card.skip_btn, Qt.LeftButton)
    assert win.tutorial_dialog is None
    assert len(win.documents) == count + int(started)
    assert win.active_document_id == (example if started else original)
    clean(win)


def test_skipping_inside_the_add_dialog_closes_the_guide(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    original = win.active_document_id
    start_example(qtbot, win)
    add_action(qtbot, win, 0, skip=True)
    assert win.tutorial_dialog is None and win.active_document_id == original
    clean(win)


def test_existing_preferences_do_not_trigger_a_new_first_run(qtbot, tmp_path, monkeypatch):
    Preferences().save(tmp_path / "preferences.json")
    win = window(qtbot, tmp_path, monkeypatch)
    win.demo = False
    win.offer_tutorial()
    assert not win.first_launch and win.tutorial_dialog is None
    clean(win)


def test_guide_and_timing_controls_remain_visible_at_compact_and_wide_sizes(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    guide = start_example(qtbot, win)
    win.insert_steps(create_action(0, "KEY_SPACE", duration=100))
    next_step(qtbot, guide)
    for name, size in (("automater", (1000, 680)), ("daylight", (1440, 960))):
        win.apply_appearance(name)
        win.resize(*size)
        guide.reveal_timing()
        qtbot.wait(100)
        assert win.centralWidget().rect().contains(guide.card.geometry())
        assert not guide.card.geometry().intersects(guide.widget_rect(win.inspector_panel))
        duration = win.action_inspector.duration
        viewport = win.action_inspector.findChild(QScrollArea).viewport()
        assert viewport.rect().contains(
            duration.rect().translated(duration.mapTo(viewport, QPoint()))
        )
    qtbot.mouseClick(guide.card.back_btn, Qt.LeftButton)
    assert guide.step == 1
    guide.reject()
    clean(win)
