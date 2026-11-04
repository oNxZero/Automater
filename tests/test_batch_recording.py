import json

from evdev import InputEvent, ecodes
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QGraphicsPathItem, QMessageBox
from test_gui import clean, window

from automater.actions import create_action
from automater.models import Script, Step
from automater.overlay import OverlayGroup, pointer_path
from automater.preferences import Preferences


def test_batch_hold_changes_only_edited_duration_and_is_one_undo(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    before = list(win.model.steps)
    win.workflow.canvas.choose_indices({0, 2})
    inspector = win.action_inspector
    assert inspector.apply_btn.isEnabled() and inspector.isVisible()
    assert inspector.duration.text() == "Mixed"
    inspector.duration.setValue(900)
    inspector.apply()
    assert win.model.steps == [
        before[0],
        Step(900, "key_up", "KEY_W"),
        before[2],
        before[3],
        Step(900, "key_up", "KEY_E"),
    ]
    assert len(win.workflow.canvas.selected_indices) == 2
    win.undo.undo()
    assert win.model.steps == before
    clean(win)


def test_batch_key_preserves_different_durations_and_random_ranges(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_script(
        Script(
            steps=create_action(0, "KEY_A", duration=100, maximum=200)
            + create_action(0, "KEY_B", duration=300, maximum=400)
        )
    )
    win.workflow.canvas.choose_indices({0, 1})
    win.action_inspector.key.set_code("KEY_F24")
    win.action_inspector.apply()
    assert [s.code for s in win.model.steps] == ["KEY_F24"] * 4
    assert [(s.delay_ms, s.delay_max_ms) for s in win.model.steps] == [
        (0, None),
        (100, 200),
        (0, None),
        (300, 400),
    ]
    clean(win)


def test_batch_validation_is_atomic_and_mixed_kinds_stay_disabled(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.workflow.canvas.choose_indices({0, 1})
    assert not win.action_inspector.apply_btn.isEnabled()
    win.load_script(
        Script(
            steps=create_action(2, duration=100, maximum=200)
            + create_action(2, duration=150, maximum=300)
        )
    )
    before = list(win.model.steps)
    win.workflow.canvas.choose_indices({0, 1})
    win.action_inspector.delay.setValue(250)
    win.action_inspector.apply()
    assert win.model.steps == before
    assert "Maximum delay" in win.status.text()
    clean(win)


def test_batch_timer_edits_both_minimum_and_maximum(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_script(Script(steps=create_action(2, duration=100) + create_action(2, duration=200)))
    win.workflow.canvas.choose_indices({0, 1})
    ins = win.action_inspector
    ins.delay.setValue(300)
    ins.delay_random.setChecked(True)
    ins.delay_max.setValue(600)
    ins.apply()
    assert all(s.delay_ms == 300 and s.delay_max_ms == 600 for s in win.model.steps)
    clean(win)


def test_left_drag_box_selects_without_modifier_and_middle_drag_pans(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    canvas = win.workflow.canvas
    win.hide_inspector()
    canvas.choose_indices(set())
    qtbot.wait(20)
    a = canvas.mapFromScene(canvas.nodes[0].sceneBoundingRect().topLeft()) - QPoint(8, 8)
    b = canvas.mapFromScene(canvas.nodes[1].sceneBoundingRect().bottomRight()) + QPoint(8, 8)
    qtbot.mousePress(canvas.viewport(), Qt.LeftButton, pos=a)
    qtbot.mouseMove(canvas.viewport(), pos=b)
    qtbot.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=b)
    assert {0, 1} <= canvas.selected_indices
    selected = set(canvas.selected_indices)
    qtbot.mousePress(canvas.viewport(), Qt.MiddleButton, pos=QPoint(100, 100))
    qtbot.mouseMove(canvas.viewport(), pos=QPoint(80, 100))
    qtbot.mouseRelease(canvas.viewport(), Qt.MiddleButton, pos=QPoint(80, 100))
    assert canvas.selected_indices == selected and canvas.pan_origin is None
    clean(win)


def setup_recording(win, monkeypatch):
    monkeypatch.setattr(win, "refresh_devices", lambda: None)
    win.monitor_ok = True
    win.countdown.setValue(0)


def feed(win):
    win.recorder.feed(InputEvent(0, 0, ecodes.EV_KEY, ecodes.KEY_A, 1))
    win.recorder.feed(InputEvent(0, 0, ecodes.EV_KEY, ecodes.KEY_A, 0))


def test_default_recording_appends_and_empty_capture_keeps_work(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    setup_recording(win, monkeypatch)
    before = list(win.model.steps)
    assert win.append_recording.isChecked()
    win.toggle_record()
    win.stop()
    assert win.model.steps == before
    win.toggle_record()
    feed(win)
    win.stop()
    assert win.model.steps[: len(before)] == before
    assert win.selected_rows()[0] == len(before)
    win.undo.undo()
    assert win.model.steps == before
    clean(win)


def test_rerecord_replaces_only_selected_actions_and_can_discard(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    setup_recording(win, monkeypatch)
    before = list(win.model.steps)
    win.workflow.canvas.choose_indices({1})
    win.rerecord_selection()
    feed(win)
    win.stop(discard_recording=True)
    assert win.model.steps == before
    win.rerecord_selection()
    feed(win)
    win.stop()
    assert win.model.steps[:2] == before[:2] and win.model.steps[-2:] == before[-2:]
    assert win.model.steps[2].code == "KEY_A"
    win.undo.undo()
    assert win.model.steps == before
    clean(win)


def test_replacement_requires_explicit_choice(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    setup_recording(win, monkeypatch)
    win.append_recording.setChecked(False)
    before = list(win.model.steps)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.No)
    win.toggle_record()
    assert not win.busy and win.model.steps == before
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    win.toggle_record()
    feed(win)
    win.stop()
    assert win.model.steps[0].code == "KEY_A" and len(win.model.steps) == 3
    clean(win)


def test_legacy_preferences_migrate_to_append_without_hiding_invalid_fields(tmp_path):
    path = tmp_path / "preferences.json"
    path.write_text(json.dumps({"version": 1, "append_recording": False, "test_mode": True}))
    prefs = Preferences.load(path)
    assert prefs.append_recording and prefs.test_mode
    prefs.append_recording = False
    prefs.save(path)
    assert not Preferences.load(path).append_recording


def test_pointer_path_is_bounded_and_exact_endpoint_is_retained():
    points = pointer_path([Step(0, "move", x=1) for _ in range(10000)], (20, 30))
    assert len(points) <= 1502 and (points[-1].x(), points[-1].y()) == (10020, 30)


def test_overlay_is_pass_through_and_cleanup_is_idempotent(qtbot):
    overlay = OverlayGroup(pointer_path([Step(0, "move", x=15, y=-10)], (200, 200)))
    for widget in overlay.windows:
        qtbot.addWidget(widget)
        assert widget.testAttribute(Qt.WA_TransparentForMouseEvents)
        assert widget.windowFlags() & Qt.WindowTransparentForInput
    overlay.show()
    qtbot.wait(20)
    overlay.close()
    qtbot.wait(20)
    overlay.close()


def test_screen_picker_does_not_emit_input_and_can_cancel(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.pick_screen_point()
    assert win.busy and not win.play_btn.isEnabled()
    win.overlay.choose((240, 180))
    assert not win.busy and win.start_enabled.isChecked()
    assert (win.start_x.value(), win.start_y.value()) == (240, 180)
    win.pick_screen_point()
    win.overlay.cancel()
    assert not win.busy
    clean(win)


def test_grid_connections_have_curves_and_hover_animates(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_controls_example()
    win.workflow.layout_choice.setCurrentIndex(2)
    curves = [
        item.path()
        for item in win.workflow.canvas.scene().items()
        if isinstance(item, QGraphicsPathItem)
    ]
    assert any(path.elementAt(i).isCurveTo() for path in curves for i in range(path.elementCount()))
    node = win.workflow.canvas.nodes[0]
    node.hovered = True
    node.transition()
    qtbot.waitUntil(lambda: node.emphasis > 0.95, timeout=500)
    node.hovered = False
    node.setSelected(False)
    node.transition()
    qtbot.waitUntil(lambda: node.emphasis < 0.05, timeout=500)
    clean(win)


def test_test_mode_has_prominent_explanation(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    assert win.preview_banner.isVisible()
    qtbot.mouseClick(win.real_inputs_btn, Qt.LeftButton)
    assert not win.test_mode.isChecked() and not win.preview_banner.isVisible()
    clean(win)


def test_local_f_keys_work_without_device_access(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.countdown.setValue(3)
    assert not win.monitor_ok
    qtbot.keyClick(win, Qt.Key_F7)
    assert win.busy
    qtbot.keyClick(win, Qt.Key_F12)
    qtbot.waitUntil(lambda: not win.busy, timeout=1500)
    clean(win)


def test_recording_cleanup_releases_modifiers_last():
    from automater.linux_input import Recorder

    recorder = Recorder()
    recorder.start()
    recorder.feed(InputEvent(0, 0, ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1))
    recorder.feed(InputEvent(0, 0, ecodes.EV_KEY, ecodes.KEY_W, 1))
    steps = recorder.stop()
    assert [s.code for s in steps if s.action == "key_up"] == ["KEY_W", "KEY_LEFTCTRL"]


def test_batch_movement_delay_retains_single_and_grouped_samples(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_script(
        Script(
            steps=[
                Step(10, "move", x=2),
                Step(15, "move", y=3),
                Step(20, "move", x=4, standalone=True),
            ]
        )
    )
    win.workflow.canvas.choose_indices({0, 1})
    assert win.action_inspector.apply_btn.isEnabled()
    win.action_inspector.delay.setValue(40)
    win.action_inspector.apply()
    assert [(s.delay_ms, s.x, s.y) for s in win.model.steps] == [(40, 2, 0), (15, 0, 3), (40, 4, 0)]
    clean(win)


def test_table_clear_and_partial_batch_do_not_edit_other_rows(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.navigate(0, 1)
    win.set_table_rows([0, 3])
    win.table_selection_changed()
    before = list(win.model.steps)
    win.action_inspector.delay.setValue(250)
    win.action_inspector.apply()
    assert win.model.steps == before and "complete actions" in win.status.text()
    win.table.clearSelection()
    assert not win.workflow.canvas.selected_indices and win.active_block is None
    clean(win)


def test_recording_accepts_first_press_before_countdown_ui_catches_up(qtbot, tmp_path, monkeypatch):
    import time

    win = window(qtbot, tmp_path, monkeypatch)
    setup_recording(win, monkeypatch)
    win.countdown.setValue(1)
    before = list(win.model.steps)
    win.begin_recording()
    assert win.record_pending and win.recorder.active
    win.recorder.feed(
        InputEvent(0, 0, ecodes.EV_KEY, ecodes.KEY_A, 1), occurred_at=win.record_deadline + 0.01
    )
    win.recorder.feed(
        InputEvent(0, 0, ecodes.EV_KEY, ecodes.KEY_A, 0), occurred_at=win.record_deadline + 0.06
    )
    # The GUI has not ticked yet. Transitioning it must preserve captured inputs.
    win.record_deadline = time.monotonic() - 0.01
    win.record_tick()
    win.stop()
    assert win.model.steps[: len(before)] == before
    assert [s.code for s in win.model.steps[len(before) : len(before) + 2]] == ["KEY_A", "KEY_A"]
    clean(win)
