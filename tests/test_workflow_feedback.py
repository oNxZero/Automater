from dataclasses import replace

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QTextCursor
from test_gui import clean, window

from automater.camera import CameraFollower
from automater.connections import FlowConnection, connection_state
from automater.engine import DryRun, PlaybackOptions, Replay
from automater.models import Script, Step
from automater.storage import load, save
from automater.workflow import blocks_for


def trace(**changes):
    data = dict(
        phase="delay",
        active_row=-1,
        last_sent_row=1,
        completed_row=1,
        last_activity_row=1,
        held_rows=(),
        completed_events=2,
        enabled_events=8,
        next_row=2,
        failed_row=-1,
        outcome="running",
        loop=1,
    )
    return {**data, **changes}


def timers(count):
    return [Step(1, "wait", standalone=True) for _ in range(count)]


def test_connections_track_running_completed_paused_failure_and_finish():
    blocks = blocks_for(timers(8))
    starts = [b.start for b in blocks]
    assert connection_state(0, blocks, starts, trace(phase="countdown")) == ""
    assert connection_state(1, blocks, starts, trace()) == "completed"
    assert connection_state(2, blocks, starts, trace()) == "running"
    assert connection_state(1, blocks, starts, trace(phase="paused")) == "paused"
    assert (
        connection_state(
            2,
            blocks,
            starts,
            trace(phase="finished", failed_row=2, last_activity_row=2, outcome="failed"),
        )
        == "failed"
    )
    done = trace(
        phase="finished",
        last_activity_row=7,
        completed_row=7,
        completed_events=8,
        outcome="finished",
    )
    assert connection_state(8, blocks, starts, done) == "completed"
    assert (
        connection_state(8, blocks, starts, {**done, "phase": "loop_gap", "outcome": "running"})
        == "completed"
    )
    assert connection_state(8, blocks, starts, {**done, "outcome": "failed"}) == "failed"


def test_connection_animation_stops_on_pause_stop_and_clear(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_script(Script(steps=timers(8)))
    qtbot.wait(20)
    canvas = win.workflow.canvas
    canvas.set_execution_trace(trace())
    edge = next(item for item in canvas.decorations[2] if isinstance(item, FlowConnection))
    assert edge.state == "running" and canvas.flow_timer.isActive()
    canvas.set_execution_trace(trace(phase="paused"))
    assert not canvas.flow_timer.isActive()
    canvas.set_execution_trace(trace(phase="finished", last_activity_row=2, outcome="stopped"))
    assert edge.state == "stopped" and not canvas.flow_timer.isActive()
    canvas.set_execution({})
    assert edge.state == "" and not canvas.flow_timer.isActive()
    clean(win)


def test_camera_never_follows_an_older_held_key_after_newer_dispatch(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_script(Script(steps=timers(10)))
    canvas = win.workflow.canvas
    canvas.set_execution_trace(trace(phase="action", active_row=7, last_sent_row=7, held_rows=(0,)))
    assert canvas.follow_target == 7
    canvas.set_execution_trace(trace(last_sent_row=7, completed_row=7, held_rows=(0,), next_row=8))
    assert canvas.follow_target == 7
    canvas.set_execution_trace(trace(phase="timer", active_row=8, last_sent_row=7, held_rows=(0,)))
    assert canvas.follow_target == 8
    clean(win)


def test_camera_does_not_overshoot_a_nearby_retarget(qapp):
    camera = CameraFollower()
    camera.move_to(QPointF(0, 0), QPointF(0, 2000))
    camera.advance(0.1)
    destination = camera.position.y() + 1
    camera.move_to(camera.position, QPointF(0, destination))
    values = []
    for _ in range(50):
        camera.advance(0.01)
        values.append(camera.position.y())
    assert max(values) <= destination
    assert all(b >= a for a, b in zip(values, values[1:]))
    camera.stop()


def test_grid_reflow_keeps_the_playback_camera_target(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_script(Script(steps=timers(80)))
    win.workflow.layout_choice.setCurrentIndex(2)
    win.hide_inspector()
    qtbot.wait(30)
    canvas = win.workflow.canvas
    canvas.choose_indices({0}, emit=False)
    canvas.set_execution_trace(trace(phase="timer", active_row=79, last_sent_row=78))
    columns = canvas.grid_columns
    win.resize(1800, 800)
    qtbot.waitUntil(lambda: canvas.grid_columns != columns)
    assert canvas.follow_target == 79
    qtbot.waitUntil(lambda: not canvas.camera.timer.isActive(), timeout=2500)
    visible = canvas.mapToScene(canvas.viewport().rect()).boundingRect()
    assert visible.intersects(canvas.nodes[79].sceneBoundingRect())
    clean(win)


def test_group_notes_panel_scrolls_in_a_small_window(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QScrollArea

    win = window(qtbot, tmp_path, monkeypatch)
    win.resize(1000, 680)
    win.load_script(Script(steps=timers(8)))
    win.workflow.canvas.choose_indices({0, 1})
    win.group_selection("Setup")
    qtbot.wait(30)
    page = win.inspector_stack.widget(3)
    assert isinstance(page, QScrollArea)
    assert page.verticalScrollBar().maximum() > 0
    assert win.group_inspector.text.height() >= 160
    assert win.group_inspector.name.height() >= 30
    clean(win)


def test_wrapped_group_headings_do_not_overlap_and_open_their_own_notes(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    steps = [
        replace(step, group_id="first" if i < 3 else "second") for i, step in enumerate(timers(6))
    ]
    win.load_script(
        Script(
            steps=steps,
            groups={
                "first": {"name": "Open program", "color": "#83b8f2"},
                "second": {"name": "Enter text", "color": "#b5a4fa"},
            },
        )
    )
    win.workflow.layout_choice.setCurrentIndex(2)
    win.hide_inspector()
    qtbot.wait(40)
    canvas = win.workflow.canvas
    assert canvas.grid_columns == 4
    frames = canvas.group_items
    a = frames["first"].header.translated(frames["first"].pos())
    b = frames["second"].header.translated(frames["second"].pos())
    assert not a.intersects(b)
    assert canvas.group_at(a.center()) == "first"
    assert canvas.group_at(b.center()) == "second"
    clean(win)


def test_invalid_group_draft_keeps_the_active_tab_and_text(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_script(Script(steps=timers(4)))
    win.workflow.canvas.choose_indices({0, 1})
    win.group_selection("Setup")
    current = win.document_tabs.currentIndex()
    identifier = win.active_document_id
    win.group_inspector.name.clear()
    win.group_inspector.text.setPlainText("Unfinished draft")
    win.document_tabs.setCurrentIndex(0)
    assert win.document_tabs.currentIndex() == current
    assert win.active_document_id == identifier
    count = win.document_tabs.count()
    win.load_script(Script())
    assert win.document_tabs.count() == count
    assert win.group_inspector.text.toPlainText() == "Unfinished draft"
    win.group_inspector.name.setText("Setup")
    assert win.group_inspector.flush()
    clean(win)


def finished_trace(script):
    replay = Replay(DryRun)
    replay.start(script, PlaybackOptions(countdown=0, speed=10))
    assert replay.join()
    return replay.timeline


def test_finished_banner_resize_does_not_reveal_stale_top_selection(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    script = Script(steps=timers(100))
    win.load_script(script)
    win.workflow.layout_choice.setCurrentIndex(2)
    win.hide_inspector()
    qtbot.wait(30)
    canvas = win.workflow.canvas
    canvas.choose_indices({0}, emit=False)
    ending = finished_trace(script)
    canvas.set_execution_trace(
        {**ending, "phase": "timer", "outcome": "running", "active_row": 98, "last_sent_row": 97}
    )
    for _ in range(20):
        canvas.camera.advance(0.03)
    values = [canvas.verticalScrollBar().value()]
    canvas.verticalScrollBar().valueChanged.connect(values.append)
    win.render_playback(ending)
    qtbot.wait(800)
    assert canvas.follow_target == 99
    assert min(values) >= values[0] - 2, values
    assert canvas.verticalScrollBar().value() > 1000
    clean(win)


def test_plus_sits_next_to_tabs_and_creates_new_workflow(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.new_script()
    qtbot.wait(25)
    tabs = win.document_tabs
    end = tabs.x() + tabs.tabRect(tabs.count() - 1).right()
    assert 0 <= win.new_tab_btn.x() - end <= 25
    before = tabs.count()
    qtbot.mouseClick(win.new_tab_btn, Qt.LeftButton)
    assert tabs.count() == before + 1 and not win.model.steps
    clean(win)


def test_one_group_rectangle_encloses_selected_actions_across_grid_rows(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_script(Script(steps=timers(16)))
    win.workflow.layout_choice.setCurrentIndex(2)
    win.workflow.canvas.choose_indices({0, 1, 7, 10})
    win.group_selection("Open program", notes="Start here")
    qtbot.wait(25)
    canvas = win.workflow.canvas
    assert len(canvas.group_items) == 1
    frame = next(iter(canvas.group_items.values()))
    for index in (0, 1, 7, 10):
        assert frame.sceneBoundingRect().contains(canvas.nodes[index].sceneBoundingRect())
    assert not win.model.steps[2].group_id
    clean(win)


def test_clicking_group_body_opens_notes_and_drag_still_box_selects(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    canvas = win.workflow.canvas
    canvas.choose_indices({0, 2})
    win.group_selection("Section", notes="Instructions")
    win.hide_inspector()
    qtbot.wait(25)
    frame = next(iter(canvas.group_items.values()))
    pos = canvas.mapFromScene(frame.pos() + QPointF(6, 85))
    qtbot.mouseClick(canvas.viewport(), Qt.LeftButton, pos=pos)
    assert win.inspector_stack.currentIndex() == 3
    assert win.group_inspector.text.toPlainText() == "Instructions"
    win.hide_inspector()
    qtbot.wait(20)
    frame = next(iter(canvas.group_items.values()))
    start = canvas.mapFromScene(frame.pos() + QPointF(6, 45))
    end = canvas.mapFromScene(canvas.nodes[0].sceneBoundingRect().bottomRight() + QPointF(3, 3))
    qtbot.mousePress(canvas.viewport(), Qt.LeftButton, pos=start)
    qtbot.mouseMove(canvas.viewport(), pos=end)
    qtbot.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=end)
    assert 0 in canvas.selected_indices
    clean(win)


def test_draft_group_notes_survive_other_edits_save_and_tab_switch(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.workflow.canvas.choose_indices({0})
    win.group_selection("Section")
    identity = next(iter(win.model.groups))
    win.group_inspector.text.setPlainText("Latest notes")
    win.add_step(2)
    assert win.model.groups[identity]["notes"] == "Latest notes"
    win.group_inspector.select(identity, win.model.groups[identity])
    win.group_inspector.text.setPlainText("Still typing")
    win.new_script()
    win.document_tabs.setCurrentIndex(0)
    assert win.model.groups[identity]["notes"] == "Still typing"
    assert win.group_inspector.identity == identity
    assert win.group_inspector.text.toPlainText() == "Still typing"
    win.path = tmp_path / "saved.json"
    assert win.save_script()
    assert load(win.path).groups[identity]["notes"] == "Still typing"
    clean(win)


def test_group_notes_save_automatically_and_keep_run_results(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.workflow.canvas.choose_indices({0})
    win.group_selection("Section")
    identity = next(iter(win.model.groups))
    ending = finished_trace(win.script())
    win.render_playback(ending)
    qtbot.wait(40)
    before = list(win.model.steps)
    win.inspect_group(identity)
    win.group_inspector.text.setPlainText("Investigate this step")
    qtbot.waitUntil(
        lambda: win.model.groups[identity].get("notes") == "Investigate this step", timeout=1500
    )
    assert win.model.steps == before and win.last_run == ending
    assert win.workflow.run_summary.isVisible()
    clean(win)


def test_group_notes_autosave_keeps_typing_position_scroll_and_edit_history(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    win.workflow.canvas.choose_indices({0})
    original = "\n".join(f"Instruction {i}" for i in range(80)) + "\n"
    win.group_selection("Section", notes=original)
    identity = win.group_inspector.identity
    editor = win.group_inspector.text
    qtbot.wait(30)
    editor.setFocus()
    editor.moveCursor(QTextCursor.End)
    qtbot.keyClicks(editor, "First sentence.")
    position = editor.textCursor().position()
    scroll = editor.verticalScrollBar().value()
    viewport = editor.viewport().size()
    assert scroll > 0 and editor.document().isUndoAvailable()
    qtbot.waitUntil(
        lambda: win.model.groups[identity].get("notes") == original + "First sentence.",
        timeout=1500,
    )
    assert editor.textCursor().position() == position
    assert editor.viewport().size() == viewport
    assert editor.verticalScrollBar().value() == scroll
    assert editor.hasFocus() and editor.document().isUndoAvailable()
    qtbot.keyClicks(editor, " Next sentence.")
    expected = original + "First sentence. Next sentence."
    qtbot.waitUntil(lambda: win.model.groups[identity].get("notes") == expected, timeout=1500)
    assert editor.toPlainText() == expected
    clean(win)


def test_saving_group_notes_keeps_text_and_name_selections(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.workflow.canvas.choose_indices({0})
    win.group_selection("Section", notes="Open the menu and wait.")
    inspector = win.group_inspector
    editor = inspector.text
    editor.moveCursor(QTextCursor.End)
    editor.insertPlainText(" Then continue.")
    cursor = editor.textCursor()
    cursor.setPosition(5)
    cursor.setPosition(13, QTextCursor.KeepAnchor)
    editor.setTextCursor(cursor)
    inspector.name.setText("Updated section")
    inspector.name.setSelection(2, 5)
    win.path = tmp_path / "notes.json"
    assert win.save_script()
    assert (editor.textCursor().anchor(), editor.textCursor().position()) == (5, 13)
    assert inspector.name.selectionStart() == 2
    assert inspector.name.selectedText() == "dated"
    assert load(win.path).groups[inspector.identity]["notes"].endswith("Then continue.")
    win.refresh_workflow()
    assert (editor.textCursor().anchor(), editor.textCursor().position()) == (5, 13)
    clean(win)


def test_legacy_cards_are_converted_without_changing_recorded_inputs(tmp_path):
    inputs = [Step(15, "key_down", "KEY_W"), Step(220, "key_up", "KEY_W")]
    old = Script(
        steps=[
            Step(0, "note", title="Setup", text="Face north"),
            *inputs,
            Step(0, "note", title="Finish", text="Check your position"),
        ]
    )
    path = tmp_path / "old.json"
    save(old, path)
    original = path.read_bytes()
    new = load(path)
    assert not any(step.action == "note" for step in new.steps)
    assert [replace(step, group_id="") for step in new.steps] == inputs
    text = "\n".join(group.get("notes", "") for group in new.groups.values())
    assert "Face north" in text and "Check your position" in text
    assert path.read_bytes() == original
    assert new.to_dict()["version"] == 4


def test_legacy_note_only_workflow_preserves_description_and_version_never_downgrades():
    data = Script(steps=[Step(0, "note", title="Reminder", text="Bindings")]).to_dict()
    new = Script.from_dict(data)
    assert not new.steps and "Bindings" in new.notes
    explicit = Script(version=4, start={"x": 0, "y": 0, "settle_ms": 0, "space": "desktop"})
    assert explicit.to_dict()["version"] == 4


def test_note_drafts_are_included_in_copy_without_collapsing_selection(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    win.workflow.canvas.choose_indices({0, 2})
    win.group_selection("Section")
    win.group_inspector.text.setPlainText("Newest notes")
    assert win.copy_selection()
    assert win.workflow.canvas.selected_indices == {0, 2}
    win.new_script()
    win.paste_selection()
    assert len(win.model.steps) == 4
    assert next(iter(win.model.groups.values()))["notes"] == "Newest notes"
    clean(win)


def test_group_drafts_work_with_toolbar_undo_redo_and_duplicate(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.workflow.canvas.choose_indices({0, 2})
    win.group_selection("Section", notes="Original")
    identity = win.group_inspector.identity
    win.group_inspector.text.setPlainText("Pending edit")
    win.undo_btn.click()
    assert win.model.groups[identity]["notes"] == "Original"
    assert not win.group_inspector.pending
    win.redo_btn.click()
    assert win.model.groups[identity]["notes"] == "Pending edit"
    win.workflow.canvas.choose_indices({0, 2})
    win.group_inspector.text.setPlainText("Copied by duplicate")
    win.duplicate()
    assert len(win.model.groups) == 2
    assert all(group["notes"] == "Copied by duplicate" for group in win.model.groups.values())
    clean(win)


def test_hidden_workflow_does_not_animate_and_resumes_at_latest_action(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_script(Script(steps=timers(30)))
    qtbot.wait(20)
    canvas = win.workflow.canvas
    canvas.set_execution_trace(trace())
    win.navigate(0, 1)
    assert not canvas.camera.timer.isActive() and not canvas.flow_timer.isActive()
    canvas.set_execution_trace(trace(last_sent_row=19, completed_row=19, next_row=20))
    assert canvas.follow_target == 19 and not canvas.camera.timer.isActive()
    win.navigate(0, 0)
    assert canvas.follow_target == 19
    clean(win)
