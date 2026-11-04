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
    def __init__(self, backend_factory, notify=lambda *args: None, rng=None):
        self.backend_factory = backend_factory
        self.notify = notify
        self.rng = rng if rng is not None else random.Random()
        self._condition = threading.Condition()
        self._stop = False
        self._paused = False
        self._thread = None

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
        )
        if snapshot.start is not None and options.start_position is None:
            options = replace(
                options,
                start_position=(snapshot.start["x"], snapshot.start["y"]),
                start_settle=snapshot.start["settle_ms"] / 1000,
            )
        if options.start_position is not None:
            options = replace(options, start_position=tuple(options.start_position))
        if not any(s.enabled for s in snapshot.steps):
            raise ValueError("Add or enable at least one step first")
        self._stop = self._paused = False
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
                    started = time.monotonic()
                    self._release(backend, held)
                    self.notify("state", "Paused • held inputs released")
                    while self._paused and not self._stop:
                        self._condition.wait(0.05)
                    deadline += time.monotonic() - started
                    if self._stop:
                        return None
                    backend.check()
                    for code in sorted(held, key=lambda code: (code not in MODIFIER_KEYS, code)):
                        backend.send(Step(0, "key_down", code))
                    self.notify("state", "Playing")
                remaining = deadline - time.monotonic()
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
        backend, held = None, set()
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
            self.notify("countdown", lead_in)
            deadline = self._wait(time.monotonic() + lead_in, _NoCheck(), held)
            if deadline is None:
                return
            backend.check()
            self.notify("state", "Playing")
            loop = 0
            last_progress = 0.0
            last_wait_report = 0.0
            while not self._stop and (options.repeats == 0 or loop < options.repeats):
                loop += 1
                self.notify("cycle", loop)
                if options.start_position is not None:
                    if self._stop:
                        return
                    backend.begin_cycle(options.start_position)
                    self.notify(
                        "state",
                        f"Loop {loop} · starting at {options.start_position[0]}, {options.start_position[1]}",
                    )
                    deadline = self._wait(time.monotonic() + options.start_settle, backend, held)
                    if deadline is None:
                        return
                for index, step in enumerate(script.steps):
                    if not step.enabled:
                        continue
                    duration = step.sample_delay(self.rng) / 1000 / options.speed
                    now = time.monotonic()
                    if (
                        duration >= 0.05
                        or now - last_wait_report >= 1 / 30
                        or index == len(script.steps) - 1
                    ):
                        self.notify("waiting", (index, loop, duration))
                        last_wait_report = now
                    deadline = self._wait(deadline + duration, backend, held)
                    if deadline is None:
                        return
                    backend.check()
                    if step.action == "key_down":
                        held.add(step.code)  # Track before send, including partially failed sends.
                    backend.send(step)
                    if step.action == "key_up":
                        held.discard(step.code)
                    # High polling-rate mice and zero-delay scripts must not flood Qt.
                    now = time.monotonic()
                    if now - last_progress >= 1 / 30 or index == len(script.steps) - 1:
                        self.notify("progress", (index, loop))
                        last_progress = now
                self._release(backend, held)
                held.clear()
                if options.repeats == 0 or loop < options.repeats:
                    # Enforce a minimum gap so an empty loop cannot spin the CPU.
                    deadline = self._wait(deadline + max(options.loop_gap, 0.01), backend, held)
                    if deadline is None:
                        return
        except Exception as exc:
            self.notify("error", str(exc))
        finally:
            if backend is not None:
                try:
                    self._release(backend, held)
                except Exception as exc:
                    self.notify("error", str(exc))
                try:
                    backend.close()
                except Exception as exc:
                    self.notify("error", str(exc))
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
