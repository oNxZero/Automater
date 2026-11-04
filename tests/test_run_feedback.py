import time
from types import SimpleNamespace

from evdev import InputEvent, ecodes
from test_engine import Backend, eventually
from test_gui import clean, window

from automater.actions import create_action
from automater.engine import PlaybackOptions, Replay
from automater.linux_input import Recorder
from automater.models import Script, Step
from automater.run_feedback import block_states
from automater.workflow import blocks_for


def test_waiting_before_first_input_does_not_mark_it_as_running():
    backend = Backend()
    replay = Replay(lambda: backend)
    script = Script(steps=[Step(10000, "key_down", "KEY_A"), Step(100, "key_up", "KEY_A")])
    replay.start(script, PlaybackOptions(countdown=0))
    eventually(lambda: replay.timeline["phase"] == "delay")
    assert not backend.events
    assert replay.timeline["active_row"] == -1
    assert not any(block_states(blocks_for(script.steps), script.steps, replay.timeline).values())
    replay.stop()
    assert replay.join()


def test_timer_and_held_inputs_are_active_until_their_deadlines():
    backend = Backend()
    replay = Replay(lambda: backend)
    script = Script(
        steps=create_action(5, "KEY_W")
        + create_action(2, duration=10000)
        + create_action(6, "KEY_W")
    )
    replay.start(script, PlaybackOptions(countdown=0))
    eventually(lambda: replay.timeline["phase"] == "timer")
    trace = replay.timeline
    assert trace["completed_row"] == 0 and trace["held_rows"] == (0,)
    assert block_states(blocks_for(script.steps), script.steps, trace) == {
        0: "running",
        1: "running",
        2: "",
    }
    replay.stop()
    assert replay.join()
    states = block_states(blocks_for(script.steps), script.steps, replay.timeline)
    assert states == {0: "completed", 1: "stopped", 2: ""}
    assert backend.events[-1].action == "key_up"


def test_completed_and_failed_rows_are_retained_after_partial_send_failure():
    class Broken(Backend):
        def send(self, step):
            super().send(step)
            if step.code == "KEY_B" and step.action == "key_down":
                raise RuntimeError("Input rejected")

    backend = Broken()
    replay = Replay(lambda: backend)
    script = Script(
        steps=create_action(0, "KEY_A", duration=0) + create_action(0, "KEY_B", duration=0)
    )
    replay.start(script, PlaybackOptions(countdown=0))
    assert replay.join()
    trace = replay.timeline
    assert trace["outcome"] == "failed" and trace["completed_row"] == 1 and trace["failed_row"] == 2
    assert block_states(blocks_for(script.steps), script.steps, trace) == {
        0: "last",
        1: "failed",
    }
    assert backend.events[-1].action == "key_up" and backend.events[-1].code == "KEY_B"


def test_countdown_uses_worker_deadline_even_when_ui_receives_it_late(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    trace = {
        "phase": "countdown",
        "phase_started": time.monotonic() - 0.5,
        "deadline": time.monotonic() + 0.5,
        "wait_duration": 1.0,
        "completed_row": -1,
        "completed_events": 0,
        "enabled_events": len(win.model.steps),
        "active_row": -1,
        "last_activity_row": -1,
        "last_sent_row": -1,
        "held_rows": (),
        "failed_row": -1,
        "outcome": "running",
        "loop": 0,
        "loop_duration": 1,
        "loop_elapsed": 0,
        "max_lateness_ms": 0,
        "error": "",
    }
    win.replay = SimpleNamespace(timeline=trace, running=False, join=lambda *args: True)
    win.on_replay("countdown", {"duration": 1.0, "deadline": trace["deadline"]})
    assert win.playback_deadline == trace["deadline"]
    assert win.countdown_progress.value() >= 490
    clean(win)


def test_finished_trace_remains_visible_and_is_specific_to_its_tab(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.countdown.setValue(0)
    win.speed.setValue(10)
    win.toggle_play()
    qtbot.waitUntil(lambda: not win.busy, timeout=2000)
    trace = dict(win.last_run)
    assert trace["outcome"] == "finished"
    assert win.workflow.run_summary.isVisible()
    assert all(
        node.execution_state in ("completed", "last") for node in win.workflow.canvas.nodes.values()
    )
    assert not any(node.playing for node in win.workflow.canvas.nodes.values())
    win.new_script()
    assert win.last_run is None and not win.workflow.run_summary.isVisible()
    win.document_tabs.setCurrentIndex(0)
    assert win.last_run == trace
    win.add_step(2)
    assert win.last_run is None and not win.workflow.run_summary.isVisible()
    clean(win)


def test_recorded_xy_axes_share_one_report_without_losing_frame_timing():
    recorder = Recorder()
    recorder.start()
    start = recorder._started
    for code, value in ((ecodes.REL_X, 5), (ecodes.REL_Y, 7)):
        recorder.feed(
            InputEvent(0, 0, ecodes.EV_REL, code, value), source="mouse", occurred_at=start + 0.01
        )
    recorder.feed(
        InputEvent(0, 0, ecodes.EV_SYN, ecodes.SYN_REPORT, 0),
        source="mouse",
        occurred_at=start + 0.01,
    )
    recorder.feed(
        InputEvent(0, 0, ecodes.EV_REL, ecodes.REL_X, 3), source="mouse", occurred_at=start + 0.02
    )
    recorder.feed(
        InputEvent(0, 0, ecodes.EV_SYN, ecodes.SYN_REPORT, 0),
        source="mouse",
        occurred_at=start + 0.02,
    )
    steps = recorder.stop()
    assert [(s.x, s.y) for s in steps[:2]] == [(5, 7), (3, 0)]
    assert all(abs(s.delay_ms - 10) < 0.01 for s in steps[:2])


def test_recorded_movement_never_combines_different_devices():
    recorder = Recorder()
    recorder.start()
    recorder.feed(InputEvent(0, 0, ecodes.EV_REL, ecodes.REL_X, 3), source="one")
    recorder.feed(InputEvent(0, 0, ecodes.EV_REL, ecodes.REL_Y, 4), source="two")
    steps = recorder.stop()
    assert [(s.x, s.y) for s in steps[:2]] == [(3, 0), (0, 4)]


def test_slow_destination_reports_lateness_and_actual_cycle_duration():
    class Slow(Backend):
        def send(self, step):
            super().send(step)
            if step.action == "key_down":
                time.sleep(0.04)

    backend = Slow()
    replay = Replay(lambda: backend)
    replay.start(Script(steps=create_action(0, "KEY_A", duration=10)), PlaybackOptions(countdown=0))
    assert replay.join()
    trace = replay.timeline
    assert trace["max_lateness_ms"] >= 25
    assert trace["actual_loop_seconds"] >= 0.035
    assert trace["loop_duration"] == 0.01


def test_target_loss_during_delay_marks_the_step_that_could_not_run():
    backend = Backend()
    replay = Replay(lambda: backend)
    replay.start(
        Script(steps=create_action(0, "KEY_A", duration=10000)), PlaybackOptions(countdown=0)
    )
    assert backend.sent.wait(1)
    backend.available = False
    assert replay.join(0.5)
    assert replay.timeline["failed_row"] == 1 and replay.timeline["completed_row"] == 0
    assert replay.timeline["outcome"] == "failed"


def test_pause_freezes_progress_without_losing_elapsed_wait(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.load_script(Script(steps=[Step(2000, "wait")]))
    win.test_mode.setChecked(True)
    win.countdown.setValue(0)
    win.toggle_play()
    qtbot.waitUntil(lambda: win.progress.value() > 30, timeout=1000)
    before = win.progress.value()
    win.pause()
    qtbot.waitUntil(lambda: win.replay.timeline["phase"] == "paused", timeout=1000)
    win.render_playback()
    frozen = win.progress.value()
    assert frozen >= before
    qtbot.wait(60)
    assert win.progress.value() == frozen
    win.stop()
    qtbot.waitUntil(lambda: not win.busy, timeout=1000)
    clean(win)


def test_recording_a_new_segment_invalidates_previous_run_marks(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.countdown.setValue(0)
    win.speed.setValue(10)
    win.toggle_play()
    qtbot.waitUntil(lambda: not win.busy, timeout=2000)
    assert win.last_run is not None
    monkeypatch.setattr(win, "refresh_devices", lambda: None)
    win.monitor_ok = True
    win.toggle_record()
    win.recorder.feed(InputEvent(0, 0, ecodes.EV_KEY, ecodes.KEY_A, 1))
    win.stop()
    assert win.last_run is None and not win.workflow.run_summary.isVisible()
    clean(win)
