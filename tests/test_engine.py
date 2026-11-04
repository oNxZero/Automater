import threading
import time

import pytest

from moonlight_studio.engine import PlaybackOptions, Replay
from moonlight_studio.models import Script, Step


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
