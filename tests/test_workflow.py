from dataclasses import replace

from PySide6.QtCore import Qt
from test_gui import clean, window

from automater.models import Script, Step
from automater.workflow import VIRTUALIZE_AFTER, blocks_for


def test_grouping_retains_events_timing_and_enabled_boundaries():
    steps = [
        Step(20, "key_down", "KEY_A"),
        Step(300, "key_up", "KEY_A"),
        Step(100, "move", x=10),
        Step(16, "move", y=-5),
        Step(50, "move", x=7, enabled=False),
        Step(100, "wait"),
    ]
    original = list(steps)
    blocks = blocks_for(steps)
    assert [(b.start, b.end) for b in blocks] == [(0, 2), (2, 4), (4, 5), (5, 6)]
    assert blocks[0].title == "Hold A"
    assert blocks[0].duration == 320
    assert blocks[1].detail == "X +10   Y -5"
    assert sum(b.duration for b in blocks) == sum(s.delay_ms for s in steps)
    assert steps == original


def test_overlapping_key_holds_are_not_collapsed():
    steps = [
        Step(0, "key_down", "KEY_LEFTSHIFT"),
        Step(50, "key_down", "KEY_A"),
        Step(50, "key_up", "KEY_LEFTSHIFT"),
        Step(50, "key_up", "KEY_A"),
    ]
    assert len(blocks_for(steps)) == 4


def test_select_and_edit_paired_action_updates_both_events(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    assert len(win.blocks) == 3
    assert win.editor_stack.currentIndex() == 0
    node = win.workflow.canvas.nodes[0]
    position = win.workflow.canvas.mapFromScene(node.sceneBoundingRect().center())
    qtbot.mouseClick(win.workflow.canvas.viewport(), Qt.LeftButton, pos=position)
    inspector = win.action_inspector
    inspector.key.setCurrentIndex(inspector.key.findData("KEY_S"))
    inspector.duration.setValue(1200)
    inspector.delay.setValue(200)
    qtbot.mouseClick(inspector.apply_btn, Qt.LeftButton)
    assert win.model.steps[:2] == [Step(200, "key_down", "KEY_S"), Step(1200, "key_up", "KEY_S")]
    assert win.selected_rows() == [0, 1]
    win.undo.undo()
    assert win.model.steps[0].code == "KEY_W"
    assert win.model.steps[1].delay_ms == 650
    clean(win)


def test_reorder_moves_complete_action_and_undo_restores(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    original = list(win.model.steps)
    win.reorder_blocks(0, 2)
    assert win.model.steps == original[2:] + original[:2]
    assert win.selected_rows() == [3, 4]
    win.undo.undo()
    assert win.model.steps == original
    clean(win)


def test_insert_between_actions_preserves_existing_events(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    original = list(win.model.steps)
    win.add_step(2, 2)
    assert win.model.steps == original[:2] + [Step(250, "wait", standalone=True)] + original[2:]
    assert win.active_block.start == 2
    clean(win)


def test_duplicate_disable_and_delete_workflow_action(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.workflow_command("duplicate")
    assert len(win.model.steps) == 7
    win.workflow_command("toggle")
    assert not win.model.steps[2].enabled and not win.model.steps[3].enabled
    win.workflow_command("delete")
    assert len(win.model.steps) == 5
    assert all(s.enabled for s in win.model.steps)
    clean(win)


def test_large_recording_has_bounded_canvas_and_retains_raw_samples(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    steps = [Step(1, "move", x=1) for _ in range(10_000)] + [Step(50) for _ in range(10_000)]
    win.load_script(Script("Long recording", steps=steps))
    qtbot.wait(20)
    assert len(win.blocks) == 10_001
    canvas = win.workflow.canvas
    assert len(canvas.nodes) < VIRTUALIZE_AFTER
    assert win.model.steps == steps
    first = canvas.node_position(0)
    canvas.reveal_index(5000)
    assert 5000 in canvas.nodes and 0 not in canvas.nodes
    assert canvas.node_position(0) == first
    assert len(canvas.nodes) < VIRTUALIZE_AFTER
    canvas.highlight(len(steps) - 1)
    qtbot.wait(800)
    assert 10000 in canvas.nodes
    assert len(canvas.nodes) < VIRTUALIZE_AFTER
    clean(win)


def test_grouped_motion_timing_edit_keeps_original_coordinates(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    steps = [Step(10, "move", x=2), Step(20, "move", y=4), Step(30, "move", x=-2)]
    win.load_script(Script("Motion", steps=steps))
    win.action_inspector.duration.setValue(100)
    win.action_inspector.apply()
    assert win.model.steps == [
        steps[0],
        replace(steps[1], delay_ms=40),
        replace(steps[2], delay_ms=60),
    ]
    clean(win)


def test_empty_workspace_and_navigation(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_script(Script())
    assert win.editor_stack.currentIndex() == 2
    win.navigate(1)
    assert win.pages.currentIndex() == 1
    assert win.library_empty.isVisible()
    win.navigate(2)
    assert win.pages.currentIndex() == 2
    win.add_step(0)
    assert win.pages.currentIndex() == 0
    assert win.editor_stack.currentIndex() == 0
    clean(win)


def test_read_only_workflow_during_replay_and_progress(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    original = list(win.model.steps)
    win.countdown.setValue(0)
    win.speed.setValue(10)
    win.toggle_play()
    win.workflow_command("delete")
    win.add_step()
    assert win.model.steps == original
    qtbot.waitUntil(lambda: not win.busy, timeout=3000)
    assert all(not n.playing for n in win.workflow.canvas.nodes.values())
    assert win.progress.value() > 0
    clean(win)


def test_event_selection_is_reflected_on_canvas(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.navigate(0, 1)
    win.table.selectRow(2)
    assert win.active_block.start == 2
    assert win.workflow.canvas.nodes[1].isSelected()
    win.navigate(0, 0)
    assert win.action_inspector.title.text() == "Timer"
    win.undo.activeStack().clear()
    clean(win)


def test_drag_card_reorders_the_source_events(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint

    win = window(qtbot, tmp_path, monkeypatch)
    original = list(win.model.steps)
    canvas = win.workflow.canvas
    canvas.fit()
    start = canvas.mapFromScene(canvas.nodes[0].sceneBoundingRect().center())
    end = start + QPoint(round(260 * canvas.transform().m11()), 0)
    qtbot.mousePress(canvas.viewport(), Qt.LeftButton, pos=start)
    qtbot.mouseMove(canvas.viewport(), pos=end)
    qtbot.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=end)
    assert win.model.steps == original[2:3] + original[:2] + original[3:]
    win.undo.undo()
    assert win.model.steps == original
    clean(win)


def test_drag_hover_previews_order_without_changing_events_and_cancel_restores(
    qtbot, tmp_path, monkeypatch
):
    from PySide6.QtCore import QPointF

    win = window(qtbot, tmp_path, monkeypatch)
    win.load_controls_example()
    qtbot.wait(20)
    canvas = win.workflow.canvas
    before = list(win.model.steps)
    canvas.choose_indices({0, 2})
    origin = canvas.node_position(0) + QPointF(50, 50)
    destination = origin + canvas.node_position(5) - canvas.node_position(0)
    canvas.preview_drag(0, origin, destination)
    assert canvas.drag_state["target"] == 5
    assert canvas.drag_state["mapping"][0] == 4
    assert canvas.drag_state["mapping"][2] == 5
    assert len(canvas.drag_items) == 2
    assert canvas.drag_preview_items
    assert win.model.steps == before
    canvas.finish_drag(cancel=True)
    assert canvas.selected_indices == {0, 2}
    assert all(node.pos() == canvas.node_position(i) for i, node in canvas.nodes.items())
    assert win.model.steps == before
    assert canvas.drag_state is None and not canvas.drag_items
    clean(win)


def test_playback_camera_has_intermediate_positions_and_can_be_disabled(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_controls_example()
    qtbot.wait(20)
    canvas = win.workflow.canvas
    canvas.resetTransform()
    canvas.reveal_index(0)
    initial = canvas.horizontalScrollBar().value()
    canvas.follow_index(5)
    assert abs(canvas.horizontalScrollBar().value() - initial) <= 2
    canvas.camera.advance(0.12)
    middle = canvas.horizontalScrollBar().value()
    canvas.camera.advance(0.8)
    final = canvas.horizontalScrollBar().value()
    assert initial < middle < final
    win.workflow.follow_btn.setChecked(False)
    canvas.follow_index(0)
    assert canvas.horizontalScrollBar().value() == final
    clean(win)
