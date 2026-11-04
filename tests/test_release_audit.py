from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from test_gui import clean, window

from automater import theme
from automater.action_dialog import ActionDialog
from automater.dialogs import GroupDialog
from automater.engine import DryRun, PlaybackOptions, Replay
from automater.models import Script, Step
from automater.palettes import PALETTES
from automater.preferences import Preferences
from automater.storage import save


def test_themes_apply_to_canvas_without_mutating_work_and_restore_on_restart(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    win.workflow.canvas.choose_indices({0, 2})
    win.group_selection("Section", color="#83b8f2", notes="Keep my notes")
    identity = win.group_inspector.identity
    editor = win.group_inspector.text
    editor.moveCursor(QTextCursor.End)
    editor.insertPlainText(" while editing")
    position = editor.textCursor().position()
    before = win.script().to_dict()
    selection = set(win.workflow.canvas.selected_indices)
    history = win.undo.activeStack().count()
    win.show_appearance()
    qtbot.wait(20)
    assert all(card.height() >= 82 for card in win.appearance_dialog.cards.values())
    win.appearance_dialog.cards["nord"].click()
    assert theme.paint_color(theme.BASE).name() == PALETTES["nord"].base
    assert win.preferences.theme == "nord"
    assert win.script().to_dict() == before
    assert win.workflow.canvas.selected_indices == selection
    assert win.undo.activeStack().count() == history
    assert win.group_inspector.identity == identity and editor.textCursor().position() == position
    assert win.appearance_dialog.cards["nord"].isChecked()
    win.apply_appearance("nord", {"accent": "#ffc266", "base": "#102028"})
    assert theme.paint_color(theme.ACCENT).name() == "#ffc266"
    prefs = Preferences.load(win.preferences_path)
    assert prefs.theme_colors == {"accent": "#ffc266", "base": "#102028"}
    other = window(qtbot, tmp_path, monkeypatch)
    assert other.preferences.theme == "nord" and theme.palette().base == "#102028"
    win.group_inspector.flush()
    clean(win)
    clean(other)


@pytest.mark.parametrize("identity", PALETTES)
def test_each_theme_renders_and_has_readable_text(qtbot, tmp_path, monkeypatch, identity):
    win = window(qtbot, tmp_path, monkeypatch)
    before = win.script().to_dict()
    win.apply_appearance(identity, {})
    p = theme.palette()
    assert theme.contrast(p.text, p.panel) >= 4.5
    assert theme.contrast(p.muted, p.base) >= 4.5
    assert theme.contrast(theme.resolve_hex("#181424"), p.accent) >= 4.5
    assert not win.grab().isNull()
    assert win.script().to_dict() == before
    clean(win)


def test_light_theme_includes_canvas_icons_and_legible_group_labels(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.apply_appearance("daylight")
    assert theme.luminance(theme.paint_color("#131724").name()) > 0.5
    assert theme.luminance(theme.paint_color(theme.TEXT).name()) < 0.1
    assert "close-light.svg" in win.styleSheet()
    assert theme.contrast(theme.legible_group_color("#e8c58a").name(), theme.palette().panel) >= 3
    assert theme.paint_color(theme.MUTED).name() == PALETTES["daylight"].muted
    assert theme.contrast(theme.paint_color("#5d5877").name(), theme.palette().base) >= 3
    win.apply_appearance("automater")
    assert theme.paint_color(theme.BASE).name() == theme.BASE
    clean(win)


@pytest.mark.parametrize(
    "fields",
    [
        {"theme": "missing"},
        {"theme_colors": {"text": "#ffffff"}},
        {"theme_colors": {"accent": "red"}},
        {"theme_colors": []},
    ],
)
def test_invalid_theme_preferences_are_rejected(fields):
    with pytest.raises(ValueError):
        Preferences(**fields).validate()


@pytest.mark.parametrize("background", ["#f5f6fa", "#888888", "#222222", "#c0a070"])
def test_background_override_auto_adjusts_text_and_can_reset(
    qtbot, tmp_path, monkeypatch, background
):
    win = window(qtbot, tmp_path, monkeypatch)
    win.apply_appearance("dracula", {"base": background})
    assert theme.contrast(theme.palette().text, theme.palette().base) >= 4.5
    assert theme.contrast(theme.palette().muted, theme.palette().base) >= 4.5
    win.apply_appearance("automater", {})
    assert win.preferences.theme_colors == {}
    clean(win)


def test_grouping_a_subset_keeps_other_members_metadata(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_script(Script(steps=[Step(100, standalone=True) for _ in range(5)]))
    win.workflow.canvas.choose_indices({0, 1, 2})
    win.group_selection("Original", notes="Existing notes")
    original = win.model.steps[0].group_id
    win.workflow.canvas.choose_indices({1})
    win.group_selection("Only this action", notes="New notes")
    fresh = win.model.steps[1].group_id
    assert fresh != original
    assert win.model.steps[0].group_id == win.model.steps[2].group_id == original
    assert win.model.groups[original]["name"] == "Original"
    assert win.model.groups[original]["notes"] == "Existing notes"
    win.undo.undo()
    assert all(step.group_id == original for step in win.model.steps[:3])
    clean(win)


def test_keyboard_undo_uses_text_editor_and_canvas_undo_uses_workflow(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.workflow.canvas.choose_indices({0})
    win.group_selection("Section", notes="Original")
    identity = win.group_inspector.identity
    editor = win.group_inspector.text
    win.activateWindow()
    qtbot.wait(30)
    editor.setFocus()
    editor.moveCursor(QTextCursor.End)
    qtbot.keyClicks(editor, " typed")
    assert win.group_inspector.flush()
    qtbot.keyClick(editor, Qt.Key_Z, Qt.ControlModifier)
    assert editor.toPlainText() == "Original"
    assert identity in win.model.groups
    assert win.group_inspector.flush()
    win.workflow.canvas.setFocus()
    win.add_step(2)
    length = len(win.model.steps)
    qtbot.keyClick(win.workflow.canvas, Qt.Key_Z, Qt.ControlModifier)
    assert len(win.model.steps) < length
    clean(win)


def test_invalid_note_draft_blocks_delete_and_cell_edits_without_losing_work(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    win.workflow.canvas.choose_indices({0})
    win.group_selection("Section", notes="Keep")
    before = list(win.model.steps)
    win.group_inspector.name.clear()
    win.group_inspector.text.setPlainText("Unfinished draft")
    win.delete()
    assert not win.model.setData(win.model.index(0, 1), 250)
    assert win.model.steps == before
    assert win.group_inspector.pending
    assert win.group_inspector.text.toPlainText() == "Unfinished draft"
    win.group_inspector.name.setText("Section")
    assert win.group_inspector.flush()
    assert win.workflow.canvas.selected_indices == {0}
    clean(win)


def test_blocked_open_and_examples_keep_current_document_and_report_truthfully(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    win.workflow.canvas.choose_indices({0})
    win.group_selection("Section")
    win.group_inspector.name.clear()
    current = win.active_document_id
    path = tmp_path / "other.json"
    save(Script("Other", steps=[Step(100)]), path)
    recent = list(win.preferences.recent_scripts)
    win.test_mode.setChecked(False)
    assert not win.open_path(path)
    assert "Opened" not in win.status.text()
    win.load_example()
    win.load_controls_example()
    assert win.active_document_id == current
    assert win.preferences.recent_scripts == recent
    assert not win.test_mode.isChecked()
    win.group_inspector.name.setText("Section")
    clean(win)


def test_new_workflows_get_distinct_names(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    for _ in range(3):
        assert win.new_script()
    names = [doc.script.name for doc in win.documents.values()]
    assert len(names) == len(set(names))
    clean(win)


@pytest.mark.parametrize("kind,x,y", [(3, -120, 40), (4, 2, -3)])
def test_move_and_scroll_are_configurable_when_created(qtbot, kind, x, y):
    dialog = ActionDialog(kind)
    qtbot.addWidget(dialog)
    dialog.x.setValue(x)
    dialog.y.setValue(y)
    dialog.add()
    assert dialog.steps[0].x == x and dialog.steps[0].y == y


def test_existing_custom_group_color_is_not_replaced_by_dialog(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    dialog = GroupDialog(win, "Custom", "#f08040", "Notes")
    qtbot.addWidget(dialog)
    assert dialog.color.currentData() == "#f08040"
    clean(win)


def test_duplicate_and_paste_keep_input_order_and_independent_group_notes(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    steps = [Step(i * 10, standalone=True) for i in range(6)]
    win.load_script(Script(steps=steps))
    win.workflow.canvas.choose_indices({1, 3})
    win.group_selection("Copy me", notes="Original explanation")
    original = win.model.steps[1].group_id
    before = list(win.model.steps)
    win.duplicate()
    assert len(win.model.steps) == 8
    copied = win.model.steps[4:6]
    assert [replace(step, group_id="") for step in copied] == [
        replace(before[i], group_id="") for i in (1, 3)
    ]
    assert copied[0].group_id != original
    assert win.model.groups[copied[0].group_id]["notes"] == "Original explanation"
    assert win.selected_rows() == [4, 5]
    win.undo.undo()
    assert win.model.steps == before
    clean(win)


def test_invalid_notes_block_recording_before_devices_or_timers(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.workflow.canvas.choose_indices({0})
    win.group_selection("Section")
    win.group_inspector.name.clear()
    win.group_inspector.text.setPlainText("Still editing")
    monkeypatch.setattr(
        win, "refresh_devices", lambda: pytest.fail("Recording should not reach device setup")
    )
    win.begin_recording()
    assert not win.busy and not win.record_pending and win.group_inspector.pending
    win.group_inspector.name.setText("Section")
    clean(win)


def test_failed_playback_validation_retains_previous_run_results(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    replay = Replay(DryRun)
    replay.start(win.script(), PlaybackOptions(countdown=0, speed=10))
    assert replay.join()
    ending = replay.timeline
    win.render_playback(ending)
    win.test_mode.setChecked(False)
    win.mode.setCurrentIndex(1)
    win.target.clear()
    win.toggle_play()
    assert win.last_run == ending
    assert win.workflow.run_summary.isVisible()
    assert "Choose a target" in win.status.text()
    clean(win)


def test_appearance_is_blocked_during_playback(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.show_appearance()
    win.load_script(Script(steps=[Step(5000)]))
    win.countdown.setValue(0)
    win.toggle_play()
    assert win.busy and not win.appearance_dialog.isEnabled()
    assert not win.apply_appearance("daylight")
    assert win.preferences.theme == "automater"
    win.stop()
    qtbot.waitUntil(lambda: not win.busy)
    assert win.appearance_dialog.isEnabled()
    clean(win)


def test_themed_canvas_icon_keeps_its_resolved_color(qapp):
    theme.activate("daylight")
    expected = theme.palette().success
    image = theme.icon("move", expected, resolved=True).pixmap(20, 20).toImage()
    assert any(
        image.pixelColor(x, y).name() == expected and image.pixelColor(x, y).alpha() > 200
        for x in range(20)
        for y in range(20)
    )
    theme.activate("automater")


def test_clearing_imported_description_keeps_editor_available_for_undo(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_script(Script(notes="Legacy description"))
    win.show_inspector(3)
    win.activateWindow()
    qtbot.wait(30)
    editor = win.group_inspector.imported_notes
    editor.setFocus()
    editor.selectAll()
    qtbot.keyClick(editor, Qt.Key_Backspace)
    assert editor.isVisible() and not editor.toPlainText()
    qtbot.keyClick(editor, Qt.Key_Z, Qt.ControlModifier)
    assert editor.toPlainText() == "Legacy description"
    clean(win)


@pytest.mark.parametrize("choice", ["discard", "cancel"])
def test_quit_with_an_invalid_group_draft_offers_discard_or_keep_editing(
    qtbot, tmp_path, monkeypatch, choice
):
    win = window(qtbot, tmp_path, monkeypatch)
    win.workflow.canvas.choose_indices({0})
    win.group_selection("Section")
    identifier = win.active_document_id
    win.group_inspector.name.clear()
    win.group_inspector.text.setPlainText("Unfinished draft")
    monkeypatch.setattr("automater.dialogs.SaveChangesDialog.ask", lambda *args: choice)
    assert win.confirm_close_documents() is (choice == "discard")
    if choice == "cancel":
        assert identifier in win.documents
        assert win.group_inspector.text.toPlainText() == "Unfinished draft"
        win.group_inspector.name.setText("Section")
    else:
        assert identifier not in win.documents
        assert not win.model.steps
    clean(win)
