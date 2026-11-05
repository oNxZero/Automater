import threading
import time

import pytest

from automater.engine import PlaybackOptions, Replay
from automater.models import Script, Step
from automater.open_windows import GuardedDesktopBackend


class Backend:
    def __init__(self):
        self.events = []
        self.sent = threading.Event()
        self.closed = False
        self.available = True
        self.fail_on = None

    def check(self):
        if not self.available:
            raise RuntimeError("Target lost")

    def send(self, step):
        self.events.append(step)
        self.sent.set()
        if step.action == self.fail_on:
            raise RuntimeError("Send failed")

    def close(self):
        self.closed = True


def run(steps, backend=None, options=None):
    backend = backend or Backend()
    messages = []
    replay = Replay(lambda: backend, lambda *args: messages.append(args))
    replay.start(Script(steps=steps), options or PlaybackOptions(countdown=0))
    return replay, backend, messages


def eventually(predicate, timeout=1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.005)
    assert predicate()


def test_stop_interrupts_long_wait_and_releases():
    replay, backend, messages = run([Step(0, "key_down", "KEY_W"), Step(3_600_000)])
    assert backend.sent.wait(1)
    start = time.monotonic()
    replay.stop()
    assert replay.join(0.5)
    assert time.monotonic() - start < 0.5
    assert backend.events[-1] == Step(0, "key_up", "KEY_W")
    assert backend.closed
    assert messages[-1][0] == "finished"


def test_pause_releases_resume_restores_and_stop_releases():
    replay, backend, messages = run([Step(0, "key_down", "KEY_W"), Step(20_000)])
    assert backend.sent.wait(1)
    replay.pause()
    eventually(lambda: len(backend.events) >= 2)
    assert backend.events[-1].action == "key_up"
    replay.pause()
    eventually(lambda: len(backend.events) >= 3)
    assert backend.events[-1].action == "key_down"
    replay.stop()
    assert replay.join()
    assert backend.events[-1].action == "key_up"


def test_stop_while_paused_does_not_restore():
    replay, backend, _ = run([Step(0, "key_down", "KEY_A"), Step(20_000)])
    assert backend.sent.wait(1)
    replay.pause()
    eventually(lambda: len(backend.events) >= 2)
    replay.stop()
    assert replay.join()
    assert sum(s.action == "key_down" for s in backend.events) == 1


def test_cleanup_after_partial_press_failure():
    backend = Backend()
    backend.fail_on = "key_down"
    replay, backend, messages = run([Step(0, "key_down", "KEY_A")], backend)
    assert replay.join()
    assert [e.action for e in backend.events] == ["key_down", "key_up"]
    assert any(k == "error" for k, v in messages)


def test_target_loss_during_long_wait_cleans_up():
    replay, backend, messages = run([Step(0, "key_down", "KEY_A"), Step(20_000)])
    assert backend.sent.wait(1)
    backend.available = False
    assert replay.join(0.5)
    assert backend.events[-1].action == "key_up"
    assert any(v == "Target lost" for k, v in messages if k == "error")


@pytest.mark.parametrize("operation", ["check", "release", "restore"])
def test_stop_stays_responsive_during_slow_destination_operations(operation):
    entered, allow, stopped = threading.Event(), threading.Event(), threading.Event()

    class SlowBackend(Backend):
        checks = 0
        presses = 0

        def check(self):
            self.checks += 1
            if operation == "check" and self.checks == 3:
                entered.set()
                allow.wait(2)

        def send(self, step):
            if step.action == "key_down":
                self.presses += 1
            if (operation == "release" and step.action == "key_up") or (
                operation == "restore" and step.action == "key_down" and self.presses == 2
            ):
                entered.set()
                allow.wait(2)
            super().send(step)

    backend = SlowBackend()
    replay, _, _ = run([Step(0, "key_down", "KEY_W"), Step(20_000)], backend)
    stopper = None
    try:
        assert backend.sent.wait(1)
        if operation != "check":
            replay.pause()
            if operation == "restore":
                eventually(lambda: replay.timeline["phase"] == "paused")
                replay.pause()
        assert entered.wait(1)

        def stop():
            replay.stop()
            stopped.set()

        stopper = threading.Thread(target=stop)
        stopper.start()
        assert stopped.wait(0.5), "Stop blocked on destination I/O"
    finally:
        allow.set()
        replay.stop()
        if stopper is not None:
            stopper.join(2)
        assert replay.join()
    assert backend.closed and backend.events[-1].action == "key_up"
    assert replay.timeline["outcome"] == "stopped"


def test_stop_during_pre_dispatch_check_does_not_send_the_next_press():
    entered, allow = threading.Event(), threading.Event()

    class SlowCheckBackend(Backend):
        checks = 0

        def check(self):
            self.checks += 1
            if self.checks == 2:
                entered.set()
                allow.wait(2)

    backend = SlowCheckBackend()
    replay, _, _ = run([Step(0, "key_down", "KEY_A")], backend)
    try:
        assert entered.wait(1)
        replay.stop()
    finally:
        allow.set()
        assert replay.join()
    assert backend.events == [] and backend.closed
    assert replay.timeline["outcome"] == "stopped"


@pytest.mark.parametrize("action", ["key_down", "move", "scroll"])
def test_stop_during_final_desktop_focus_check_blocks_new_input(action):
    entered, allow = threading.Event(), threading.Event()
    backend = Backend()
    checks = 0

    def check_focus():
        nonlocal checks
        checks += 1
        if checks == 3:
            entered.set()
            allow.wait(2)

    replay = Replay(lambda: GuardedDesktopBackend(backend, check_focus))
    replay.start(
        Script(steps=[Step(0, action, "KEY_A" if action == "key_down" else "", x=1)]),
        PlaybackOptions(countdown=0),
    )
    try:
        assert entered.wait(1)
        replay.stop()
    finally:
        allow.set()
        assert replay.join()
    assert not any(step.action == action for step in backend.events)
    assert replay.timeline["outcome"] == "stopped" and not replay.timeline["error"]
    assert replay.timeline["completed_events"] == 0
    assert backend.closed


def test_stop_during_desktop_cursor_focus_check_does_not_move_pointer():
    entered, allow = threading.Event(), threading.Event()
    backend = Backend()
    positions = []
    backend.prepare_start = lambda point: None
    backend.begin_cycle = positions.append
    checks = 0

    def check_focus():
        nonlocal checks
        checks += 1
        if checks == 2:
            entered.set()
            allow.wait(2)

    replay = Replay(lambda: GuardedDesktopBackend(backend, check_focus))
    replay.start(
        Script(steps=[Step(0, "key_down", "KEY_A")]),
        PlaybackOptions(countdown=0, start_position=(20, 30), start_settle=0),
    )
    try:
        assert entered.wait(1)
        replay.stop()
    finally:
        allow.set()
        assert replay.join()
    assert not positions and not backend.events and backend.closed
    assert replay.timeline["outcome"] == "stopped" and not replay.timeline["error"]


def test_stop_during_desktop_resume_focus_check_does_not_restore_held_keys():
    entered, allow = threading.Event(), threading.Event()
    backend = Backend()
    restoring = False
    checks = 0

    def check_focus():
        nonlocal checks
        if restoring:
            checks += 1
            if checks == 2:
                entered.set()
                allow.wait(2)

    replay = Replay(lambda: GuardedDesktopBackend(backend, check_focus))
    replay.start(
        Script(steps=[Step(0, "key_down", "KEY_W"), Step(20_000)]),
        PlaybackOptions(countdown=0),
    )
    try:
        assert backend.sent.wait(1)
        replay.pause()
        eventually(lambda: replay.timeline["phase"] == "paused")
        restoring = True
        replay.pause()
        assert entered.wait(1)
        replay.stop()
    finally:
        allow.set()
        replay.stop()
        assert replay.join()
    assert sum(step.action == "key_down" for step in backend.events) == 1
    assert backend.events[-1].action == "key_up" and backend.closed
    assert replay.timeline["outcome"] == "stopped" and not replay.timeline["error"]


def test_repeat_disabled_steps_and_speed():
    replay, backend, _ = run(
        [Step(500, "key_down", "KEY_A", enabled=False), Step(50, "key_down", "KEY_B")],
        options=PlaybackOptions(countdown=0, repeats=2, speed=10, loop_gap=0),
    )
    assert replay.join()
    assert [(e.action, e.code) for e in backend.events] == [
        ("key_down", "KEY_B"),
        ("key_up", "KEY_B"),
        ("key_down", "KEY_B"),
        ("key_up", "KEY_B"),
    ]


def test_countdown_can_be_cancelled_before_input():
    replay, backend, _ = run([Step(0, "key_down", "KEY_A")], options=PlaybackOptions(countdown=30))
    replay.stop()
    assert replay.join(0.5)
    assert backend.events == []


def test_infinite_loop_is_stoppable():
    replay, backend, _ = run([Step(0)], options=PlaybackOptions(countdown=0, repeats=0, loop_gap=0))
    assert backend.sent.wait(1)
    replay.stop()
    assert replay.join(0.5)


def test_reject_empty_and_concurrent_start():
    replay = Replay(Backend)
    with pytest.raises(ValueError):
        replay.start(Script())
    replay.start(Script(steps=[Step(20_000)]), PlaybackOptions(countdown=0))
    with pytest.raises(RuntimeError):
        replay.start(Script(steps=[Step()]))
    replay.stop()
    assert replay.join()


@pytest.mark.parametrize(
    "kwargs",
    [{"speed": 0}, {"speed": float("nan")}, {"repeats": -1}, {"repeats": True}, {"countdown": 31}],
)
def test_bad_options(kwargs):
    with pytest.raises(ValueError):
        PlaybackOptions(**kwargs)


def test_device_registration_wait_is_cancellable_before_first_event():
    backend = Backend()
    backend.startup_delay = 0.5
    replay, backend, _ = run([Step(0, "key_down", "KEY_A")], backend)
    assert not backend.sent.wait(0.02)
    replay.stop()
    assert replay.join(0.3)
    assert backend.events == [] and backend.closed


def test_pause_restores_modifiers_before_other_held_keys():
    replay, backend, _ = run(
        [Step(0, "key_down", "KEY_LEFTSHIFT"), Step(0, "key_down", "KEY_A"), Step(20_000)]
    )
    eventually(lambda: len(backend.events) >= 2)
    replay.pause()
    eventually(lambda: len(backend.events) >= 4)
    assert [s.code for s in backend.events[2:4]] == ["KEY_A", "KEY_LEFTSHIFT"]
    replay.pause()
    eventually(lambda: len(backend.events) >= 6)
    assert [s.code for s in backend.events[4:6]] == ["KEY_LEFTSHIFT", "KEY_A"]
    replay.stop()
    assert replay.join()


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class ScheduledReplay(Replay):
    """Deterministic scheduler wakeup overshoot; no operating-system timing assumptions."""

    def _wait(self, deadline, backend, held):
        self.clock.now = max(self.clock.now, deadline + 0.0001)
        return deadline


def test_mouse_report_schedule_does_not_accumulate_wakeup_or_dispatch_cost():
    clock = FakeClock()
    backend = Backend()
    stamps = []

    def send(step):
        stamps.append(clock())
        clock.now += 0.0002

    backend.send = send
    replay = ScheduledReplay(lambda: backend, clock=clock)
    replay.start(
        Script(steps=[Step(1, "move", x=1) for _ in range(1000)]), PlaybackOptions(countdown=0)
    )
    assert replay.join()
    assert stamps[-1] - stamps[0] == pytest.approx(0.999, abs=0.00001)
    assert replay.timeline["actual_loop_seconds"] == pytest.approx(1.0003, abs=0.00001)
    assert backend.closed


def test_late_key_and_mouse_presses_keep_their_recorded_hold_duration():
    for code in ("KEY_A", "BTN_LEFT"):
        clock = FakeClock()
        backend = Backend()
        stamps = []

        def send(step):
            stamps.append((step.action, clock()))
            if step.action == "key_down":
                clock.now += 0.04  # Slow dispatch must not consume the requested hold.

        backend.send = send
        replay = ScheduledReplay(lambda: backend, clock=clock)
        replay.start(
            Script(steps=[Step(0, "key_down", code), Step(10, "key_up", code)]),
            PlaybackOptions(countdown=0),
        )
        assert replay.join()
        assert stamps[1][1] - stamps[0][1] >= 0.05
        assert replay.timeline["max_lateness_ms"] >= 40


def test_delayed_release_does_not_collapse_gap_before_next_press():
    clock = FakeClock()
    backend = Backend()
    stamps = []

    def send(step):
        stamps.append((step.action, clock()))
        clock.now += 0.04

    backend.send = send
    replay = ScheduledReplay(lambda: backend, clock=clock)
    replay.start(
        Script(
            steps=[
                Step(0, "key_down", "KEY_A"),
                Step(10, "key_up", "KEY_A"),
                Step(20, "key_down", "KEY_A"),
                Step(10, "key_up", "KEY_A"),
            ]
        ),
        PlaybackOptions(countdown=0),
    )
    assert replay.join()
    assert stamps[2][1] - stamps[1][1] >= 0.06
