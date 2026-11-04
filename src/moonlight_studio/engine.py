"""Interruptible replay with a monotonic clock, independent of the GUI loop."""

import random
import threading
import time
from dataclasses import dataclass, replace

from .models import Script, Step, number

MODIFIER_KEYS = {
    "KEY_LEFTSHIFT",
    "KEY_RIGHTSHIFT",
    "KEY_LEFTCTRL",
    "KEY_RIGHTCTRL",
    "KEY_LEFTALT",
    "KEY_RIGHTALT",
    "KEY_LEFTMETA",
    "KEY_RIGHTMETA",
}


@dataclass(frozen=True)
class PlaybackOptions:
    speed: float = 1.0
    repeats: int = 1
    countdown: float = 3.0
    loop_gap: float = 0.25
    start_position: tuple[int, int] | None = None
    start_settle: float = 0.15

    def __post_init__(self):
        number(self.speed, "Speed", 0.1, 10)
        number(self.countdown, "Countdown", 0, 30)
        number(self.loop_gap, "Loop gap", 0, 3600)
        number(self.start_settle, "Cursor settle delay", 0, 10)
        if self.start_position is not None:
            from .pointer import coordinate

            if not isinstance(self.start_position, (tuple, list)) or len(self.start_position) != 2:
                raise ValueError("Starting point must contain X and Y")
            for value in self.start_position:
                coordinate(value)
        if type(self.repeats) is not int or not 0 <= self.repeats <= 100_000:
            raise ValueError("Repeat count must be 0 (until stopped) through 100,000")


class Replay:
    def __init__(self, backend_factory, notify=lambda *args: None, rng=None, clock=None):
        self.clock = clock or time.monotonic
        self.backend_factory = backend_factory
        self.notify = notify
        self.rng = rng if rng is not None else random.Random()
        self._condition = threading.Condition()
        self._stop = False
        self._paused = False
        self._thread = None
        self._timeline_lock = threading.Lock()
        self._timeline = None

    @property
    def timeline(self):
        with self._timeline_lock:
            return dict(self._timeline) if self._timeline is not None else None

    def _publish(self, phase=None, **values):
        with self._timeline_lock:
            if phase is not None:
                values.update(phase=phase)
                values.setdefault("phase_started", self.clock())
            self._timeline.update(values)

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, script: Script, options=PlaybackOptions()):
        if self.running:
            raise RuntimeError("Playback is already running")
        script.validate()
        snapshot = Script(
            script.name,
            script.notes,
            list(script.steps),
            script.version,
            dict(script.start) if script.start is not None else None,
            {key: dict(value) for key, value in script.groups.items()},
        )
        if snapshot.start is not None and options.start_position is None:
            options = replace(
                options,
                start_position=(snapshot.start["x"], snapshot.start["y"]),
                start_settle=snapshot.start["settle_ms"] / 1000,
            )
        if options.start_position is not None:
            options = replace(options, start_position=tuple(options.start_position))
        if not any(s.runnable for s in snapshot.steps):
            raise ValueError("Add or enable at least one step first")
        self._stop = self._paused = False
        self._timeline = {
            "phase": "preparing",
            "phase_started": self.clock(),
            "deadline": None,
            "active_row": -1,
            "last_sent_row": -1,
            "completed_row": -1,
            "last_activity_row": -1,
            "held_rows": (),
            "completed_events": 0,
            "enabled_events": sum(s.runnable for s in snapshot.steps),
            "loop": 0,
            "loop_elapsed": 0.0,
            "loop_duration": 0.0,
            "wait_duration": 0.0,
            "loop_started": None,
            "paused_seconds": 0.0,
            "max_lateness_ms": 0.0,
            "error": "",
            "failed_row": -1,
            "outcome": "running",
        }
        self._thread = threading.Thread(target=self._run, args=(snapshot, options), daemon=True)
        self._thread.start()

    def stop(self):
        with self._condition:
            self._stop = True
            self._condition.notify_all()

    def pause(self):
        with self._condition:
            self._paused = not self._paused
            self._condition.notify_all()

    def join(self, timeout=2):
        if self._thread:
            self._thread.join(timeout)
        return not self.running

    def _wait(self, deadline, backend, held):
        with self._condition:
            while not self._stop:
                if self._paused:
                    started = self.clock()
                    before_pause = self.timeline
                    self._release(backend, held)
                    partial = max(
                        0,
                        min(
                            before_pause.get("wait_duration", 0),
                            before_pause.get("wait_duration", 0) - max(0, deadline - started),
                        ),
                    )
                    self._publish("paused", deadline=None, paused_wait_elapsed=partial)
                    self.notify("state", "Paused • held inputs released")
                    while self._paused and not self._stop:
                        self._condition.wait(0.05)
                    try:
                        if not self._stop:
                            backend.check()
                            for code in sorted(
                                held, key=lambda code: (code not in MODIFIER_KEYS, code)
                            ):
                                backend.send(Step(0, "key_down", code))
                    finally:
                        # Restoring a slow destination is part of the pause too.
                        paused_for = self.clock() - started
                        deadline += paused_for
                        self._publish(paused_seconds=self.timeline["paused_seconds"] + paused_for)
                    if self._stop:
                        return None
                    self.notify("state", "Playing")
                    self._publish(
                        before_pause["phase"],
                        deadline=deadline,
                        phase_started=before_pause["phase_started"] + paused_for,
                    )
                remaining = deadline - self.clock()
                if remaining <= 0:
                    return deadline
                self._condition.wait(min(remaining, 0.05))
                backend.check()
        return None

    @staticmethod
    def _release(backend, held):
        failures = []
        for code in sorted(held, key=lambda code: (code in MODIFIER_KEYS, code)):
            try:
                backend.send(Step(0, "key_up", code))
            except Exception as exc:
                failures.append(str(exc))
        if failures:
            raise RuntimeError("Could not release inputs: " + "; ".join(failures))

    def _run(self, script, options):
        backend, held, held_rows = None, set(), {}
        try:
            backend = self.backend_factory()
            if hasattr(backend, "prepare"):
                backend.prepare(script.steps)
            if options.start_position is not None:
                if script.start is not None and getattr(
                    backend, "coordinate_space", script.start["space"]
                ) not in (None, script.start["space"]):
                    raise ValueError(
                        "The script starting point uses a different coordinate space from the selected destination"
                    )
                backend.prepare_start(options.start_position)
            lead_in = max(options.countdown, getattr(backend, "startup_delay", 0))
            self.notify("state", f"Starting in {lead_in:g}s…")
            # Targets need only be focused when the countdown finishes.
            countdown_start = self.clock()
            countdown_end = countdown_start + lead_in
            self._publish("countdown", deadline=countdown_end, wait_duration=lead_in)
            self.notify("countdown", {"duration": lead_in, "deadline": countdown_end})
            deadline = self._wait(countdown_end, _NoCheck(), held)
            if deadline is None:
                return
            if hasattr(backend, "activate"):
                self._publish("activating", deadline=None, wait_duration=0.0)
                self.notify("state", "Bringing the selected window forward…")
                backend.activate()
                if self._stop:
                    return
            backend.check()
            self.notify("state", "Playing")
            loop = 0
            last_progress = 0.0
            last_wait_report = 0.0
            failed_row = -1
            while not self._stop and (options.repeats == 0 or loop < options.repeats):
                loop += 1
                scheduled = []
                for index, step in enumerate(script.steps):
                    if index % 512 == 0 and self._stop:
                        return
                    if step.runnable:
                        scheduled.append(
                            (index, step, step.sample_delay(self.rng) / 1000 / options.speed)
                        )
                total = sum(duration for _, _, duration in scheduled)
                elapsed, completed = 0.0, 0
                transitions = {}
                self._publish(
                    "positioning" if options.start_position is not None else "running",
                    loop=loop,
                    active_row=-1,
                    last_sent_row=-1,
                    last_activity_row=-1,
                    held_rows=(),
                    completed_row=-1,
                    completed_events=0,
                    loop_elapsed=0.0,
                    loop_duration=total,
                    loop_started=None,
                    loop_finished_at=None,
                    paused_seconds=0.0,
                    deadline=None,
                    wait_duration=0.0,
                )
                self.notify("cycle", loop)
                if options.start_position is not None:
                    if self._stop:
                        return
                    backend.begin_cycle(options.start_position)
                    self.notify(
                        "state",
                        f"Loop {loop} · starting at {options.start_position[0]}, {options.start_position[1]}",
                    )
                    settle_end = self.clock() + options.start_settle
                    self._publish(
                        "settling", deadline=settle_end, wait_duration=options.start_settle
                    )
                    deadline = self._wait(settle_end, backend, held)
                    if deadline is None:
                        return
                # Scheduling/preflight work must not consume the first action's delay.
                deadline = self.clock()
                for index, step, duration in scheduled:
                    if completed == 0:
                        self._publish(loop_started=deadline, paused_seconds=0.0)
                    nominal_deadline = deadline + duration
                    dispatch_deadline = nominal_deadline
                    if step.action in ("key_down", "key_up") and step.code in transitions:
                        pressed_at, logical_at, paused_at = transitions[step.code]
                        requested_hold = max(0, elapsed + duration - logical_at)
                        dispatch_deadline = max(
                            nominal_deadline,
                            pressed_at
                            + requested_hold
                            + self.timeline["paused_seconds"]
                            - paused_at,
                        )
                    activity = {"last_activity_row": index} if step.action == "wait" else {}
                    self._publish(
                        "timer" if step.action == "wait" else "delay",
                        active_row=index if step.action == "wait" else -1,
                        next_row=index,
                        deadline=dispatch_deadline,
                        wait_duration=max(0, dispatch_deadline - self.clock()),
                        loop_elapsed=elapsed,
                    )
                    if activity:
                        self._publish(**activity)
                    now = self.clock()
                    if (
                        duration >= 0.05
                        or now - last_wait_report >= 1 / 30
                        or index == len(script.steps) - 1
                    ):
                        self.notify("waiting", (index, loop, duration))
                        last_wait_report = now
                    waited_until = self._wait(dispatch_deadline, backend, held)
                    if waited_until is None:
                        return
                    # Only pauses shift the recorded timeline. Scheduler overshoot and
                    # per-event dispatch costs must not accumulate across mouse reports.
                    deadline = nominal_deadline + (waited_until - dispatch_deadline)
                    backend.check()
                    failed_row = index
                    sent_at = self.clock()
                    lateness = max(0.0, (sent_at - deadline) * 1000)
                    if step.action == "key_down":
                        held.add(step.code)  # Track before send, including partially failed sends.
                        held_rows[step.code] = index
                    backend.send(step)
                    if step.action in ("key_down", "key_up"):
                        transitions[step.code] = (
                            self.clock(),
                            elapsed + duration,
                            self.timeline["paused_seconds"],
                        )
                    if step.action == "key_up":
                        held.discard(step.code)
                        held_rows.pop(step.code, None)
                    elapsed += duration
                    completed += 1
                    self._publish(
                        "action",
                        active_row=index,
                        last_sent_row=index,
                        last_activity_row=index,
                        held_rows=tuple(held_rows.values()),
                        completed_row=index,
                        completed_events=completed,
                        loop_elapsed=elapsed,
                        deadline=None,
                        wait_duration=0.0,
                        max_lateness_ms=max(lateness, self.timeline["max_lateness_ms"]),
                    )
                    failed_row = -1
                    # High polling-rate mice and zero-delay scripts must not flood Qt.
                    now = self.clock()
                    if now - last_progress >= 1 / 30 or index == len(script.steps) - 1:
                        self.notify("progress", (index, loop))
                        last_progress = now
                self._release(backend, held)
                held.clear()
                held_rows.clear()
                self._publish(loop_finished_at=self.clock())
                if options.repeats == 0 or loop < options.repeats:
                    # Enforce a minimum gap so an empty loop cannot spin the CPU.
                    gap = max(options.loop_gap, 0.01)
                    gap_end = self.clock() + gap
                    self._publish("loop_gap", active_row=-1, deadline=gap_end, wait_duration=gap)
                    deadline = self._wait(gap_end, backend, held)
                    if deadline is None:
                        return
        except Exception as exc:
            current = self.timeline
            error_row = locals().get("failed_row", -1)
            if error_row < 0:
                error_row = current["active_row"]
                if error_row < 0 and current["phase"] in ("delay", "timer"):
                    error_row = current.get("next_row", -1)
            self._publish(
                error=str(exc),
                failed_row=error_row,
            )
            self.notify("error", str(exc))
        finally:
            if backend is not None:
                try:
                    self._release(backend, held)
                except Exception as exc:
                    self._publish(error=str(exc))
                    self.notify("error", str(exc))
                try:
                    backend.close()
                except Exception as exc:
                    self._publish(error=str(exc))
                    self.notify("error", str(exc))
            current = self.timeline
            partial = (
                current.get("paused_wait_elapsed", 0)
                if current["phase"] == "paused"
                else (
                    max(
                        0,
                        min(
                            current["wait_duration"],
                            current["wait_duration"] - max(0, current["deadline"] - self.clock()),
                        ),
                    )
                    if current["phase"] in ("delay", "timer")
                    and current.get("deadline") is not None
                    else 0.0
                )
            )
            self._publish(
                "finished",
                deadline=None,
                partial_wait_seconds=partial,
                actual_loop_seconds=max(
                    0,
                    (current.get("loop_finished_at") or self.clock())
                    - current["loop_started"]
                    - current["paused_seconds"],
                )
                if current.get("loop_started") is not None
                else 0.0,
                outcome="failed" if current["error"] else "stopped" if self._stop else "finished",
            )
            self.notify("finished", None)


class _NoCheck:
    def check(self):
        pass

    def send(self, step):
        pass


class DryRun:
    """Exercises scheduling without opening any input device."""

    coordinate_space = None

    def check(self):
        pass

    def prepare_start(self, point):
        pass

    def begin_cycle(self, point):
        pass

    def send(self, step):
        pass

    def close(self):
        pass
