import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from test_gui import clean, window

from moonlight_studio.action_dialog import ActionDialog
from moonlight_studio.actions import create_action, decode_steps, encode_steps, randomize_steps
from moonlight_studio.models import Script, Step
from moonlight_studio.storage import load, save
from moonlight_studio.workflow import blocks_for


def test_press_hold_release_timer_and_extended_keys():
    press = create_action(5, "KEY_F24")
    release = create_action(6, "KEY_F24")
    assert press[0].action == "key_down" and release[0].action == "key_up"
    assert len(blocks_for(press + release)) == 2
    hold = create_action(0, "KEY_LEFTSHIFT", duration=700, maximum=900)
    assert len(blocks_for(hold)) == 1
    assert hold[1].delay_ms == 700 and hold[1].maximum_ms == 900
    assert create_action(2, duration=250)[0].action == "wait"
    assert create_action(5, "KEY_MACRO1")[0].code == "KEY_MACRO1"


def test_v1_remains_v1_and_advanced_scripts_round_trip(tmp_path):
    old = Script(steps=[Step(500)])
    assert old.to_dict()["version"] == 1
    assert "standalone" not in old.to_dict()["steps"][0]
    advanced = Script(
        "Advanced",
        steps=create_action(0, "KEY_E", duration=100, maximum=200),
        start={"x": 12, "y": 34, "settle_ms": 150, "space": "desktop"},
    )
    path = tmp_path / "advanced.json"
    save(advanced, path)
    result = load(path)
    assert result.version == 2 and result.start == advanced.start
    assert result.steps == advanced.steps


@pytest.mark.parametrize("maximum", [-1, float("nan"), float("inf"), 3_600_001, True])
def test_invalid_timing_ranges_are_rejected(maximum):
    with pytest.raises(ValueError):
        Step(100, delay_max_ms=maximum)


def test_clipboard_retains_randomization_and_standalone_metadata():
    steps = (
        create_action(5, "KEY_W")
        + create_action(2, duration=100, maximum=200)
        + create_action(6, "KEY_W")
    )
    assert decode_steps(encode_steps(steps)) == steps
    with pytest.raises(ValueError):
        decode_steps(json.dumps({"steps": []}).encode())


def test_randomization_does_not_change_original_or_coordinates():
    steps = [Step(100, "move", x=12), Step(500)]
    result = randomize_steps(steps, [0], 20)
    assert result[0].delay_ms == 80 and result[0].maximum_ms == 120
    assert result[0].x == 12 and result[1] == steps[1]
    assert steps[0].delay_max_ms is None


def test_searchable_key_picker_and_action_dialog(qtbot):
    dialog = ActionDialog(5)
    qtbot.addWidget(dialog)
    dialog.key.setEditText("KEY_F12")
    dialog.add()
    assert dialog.steps[0].code == "KEY_F12"
    assert dialog.steps[0].standalone
    timer = ActionDialog(2)
    qtbot.addWidget(timer)
    timer.duration.setValue(200)
    timer.random.setChecked(True)
    timer.maximum.setValue(400)
    timer.add()
    assert timer.steps == [Step(200, "wait", delay_max_ms=400, standalone=True)]


def test_multi_selection_copy_cut_paste_and_undo(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    original = list(win.model.steps)
    win.workflow.canvas.choose_indices({0, 2})
    assert win.selected_rows() == [0, 1, 3, 4]
    assert win.active_block is None
    win.workflow_command("copy")
    win.workflow_command("paste")
    assert win.model.steps == original + original[:2] + original[3:]
    assert len(win.workflow.canvas.selected_indices) == 2
    win.workflow_command("cut")
    assert win.model.steps == original
    win.undo.undo()
    assert len(win.model.steps) == 9
    win.undo.undo()
    assert win.model.steps == original
    QApplication.clipboard().clear()
    clean(win)


def test_canvas_shortcuts_select_all_duplicate_delete(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    canvas = win.workflow.canvas
    canvas.setFocus()
    qtbot.keyClick(canvas, Qt.Key_A, Qt.ControlModifier)
    assert win.selected_rows() == list(range(5))
    qtbot.keyClick(canvas, Qt.Key_C, Qt.ControlModifier)
    qtbot.keyClick(canvas, Qt.Key_D, Qt.ControlModifier)
    assert len(win.model.steps) == 10
    qtbot.keyClick(canvas, Qt.Key_Delete)
    assert len(win.model.steps) == 5
    QApplication.clipboard().clear()
    clean(win)


def test_control_click_and_shift_range_selection(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.hide_inspector()
    canvas = win.workflow.canvas
    canvas.fit()
    second = canvas.mapFromScene(canvas.nodes[1].sceneBoundingRect().center())
    qtbot.mouseClick(canvas.viewport(), Qt.LeftButton, Qt.ControlModifier, pos=second)
    assert canvas.selected_indices == {0, 1}
    third = canvas.mapFromScene(canvas.nodes[2].sceneBoundingRect().center())
    qtbot.mouseClick(canvas.viewport(), Qt.LeftButton, Qt.ShiftModifier, pos=third)
    assert canvas.selected_indices == {1, 2}
    qtbot.keyRelease(canvas, Qt.Key_Shift)
    clean(win)


@pytest.mark.parametrize("mode", ["horizontal", "vertical", "grid"])
def test_layout_changes_do_not_change_data_or_selection(qtbot, tmp_path, monkeypatch, mode):
    win = window(qtbot, tmp_path, monkeypatch)
    original = list(win.model.steps)
    win.workflow.canvas.choose_indices({0, 2})
    win.workflow.layout_choice.setCurrentIndex(win.workflow.layout_choice.findData(mode))
    assert win.model.steps == original
    assert win.workflow.canvas.selected_indices == {0, 2}
    assert win.preferences.layout == mode
    clean(win)


def test_starting_point_saved_with_script_and_reset_for_another(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.start_enabled.setChecked(True)
    win.start_x.setValue(400)
    win.start_y.setValue(250)
    win.path = tmp_path / "point.json"
    assert win.save_script()
    assert load(win.path).start["x"] == 400
    win.load_script(Script())
    assert not win.start_enabled.isChecked()
    win.open_path(tmp_path / "point.json")
    assert win.start_enabled.isChecked() and win.start_x.value() == 400
    assert not win.dirty()
    clean(win)


def test_countdown_visible_and_cancel_does_not_start(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.countdown.setValue(10)
    win.toggle_play()
    qtbot.waitUntil(lambda: win.countdown_banner.isVisible(), timeout=1000)
    assert int(win.countdown_number.text()) > 0
    win.stop()
    qtbot.waitUntil(lambda: not win.busy, timeout=1000)
    assert not win.countdown_banner.isVisible()
    clean(win)


def test_precise_event_paste_selection_does_not_expand_into_neighbouring_hold(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    original = list(win.model.steps)
    win.navigate(0, 1)
    win.table.selectRow(0)
    assert win.selected_rows() == [0], (
        f"Selection did not initialize: {QApplication.keyboardModifiers()}"
    )
    win.workflow_command("copy")
    win.workflow_command("paste")
    assert win.selected_rows() == [1]
    win.workflow_command("delete")
    assert win.model.steps == original
    QApplication.clipboard().clear()
    clean(win)


def test_select_all_across_continuous_workflow_and_remove(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    steps = [Step(50, "wait", standalone=True) for _ in range(130)]
    win.load_script(Script("Large", steps=steps))
    win.workflow_command("select_all")
    assert len(win.workflow.canvas.selected_indices) == 130
    assert len(win.workflow.canvas.nodes) == 130
    win.workflow_command("delete")
    assert not win.model.steps
    win.undo.undo()
    assert win.model.steps == steps
    clean(win)


def test_shift_drag_box_selects_actions(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QPointF

    win = window(qtbot, tmp_path, monkeypatch)
    canvas = win.workflow.canvas
    canvas.choose_indices(set())
    QApplication.processEvents()
    canvas.fit()
    first = canvas.nodes[0].sceneBoundingRect()
    second = canvas.nodes[1].sceneBoundingRect()
    start = canvas.mapFromScene(first.topLeft() - QPointF(15, 15))
    end = canvas.mapFromScene(second.bottomRight() + QPointF(15, 15))
    qtbot.mousePress(canvas.viewport(), Qt.LeftButton, Qt.ShiftModifier, pos=start)
    qtbot.mouseMove(canvas.viewport(), pos=end)
    qtbot.mouseRelease(canvas.viewport(), Qt.LeftButton, Qt.ShiftModifier, pos=end)
    qtbot.keyRelease(canvas, Qt.Key_Shift)
    assert canvas.selected_indices == {0, 1}
    clean(win)


def test_noncontiguous_actions_move_as_a_group(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    steps = [Step(i + 1, "wait", standalone=True) for i in range(4)]
    win.load_script(Script("Move", steps=steps))
    win.workflow.canvas.choose_indices({0, 2})
    win.reorder_blocks(0, 3)
    assert win.model.steps == [steps[1], steps[3], steps[0], steps[2]]
    assert win.workflow.canvas.selected_indices == {2, 3}
    win.undo.undo()
    assert win.model.steps == steps
    clean(win)


def test_paste_shortcut_works_in_empty_workspace(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.workflow_command("select_all")
    win.workflow_command("copy")
    original = list(win.model.steps)
    win.load_script(Script())
    win.save_btn.setFocus()
    qtbot.keyClick(win, Qt.Key_V, Qt.ControlModifier)
    assert win.model.steps == original
    QApplication.clipboard().clear()
    clean(win)


def test_text_shortcuts_do_not_delete_workflow_actions(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    original = list(win.model.steps)
    win.name.setFocus()
    qtbot.keyClick(win.name, Qt.Key_A, Qt.ControlModifier)
    qtbot.keyClick(win.name, Qt.Key_Delete)
    assert win.model.steps == original
    win.name.setText("Renamed")
    clean(win)
