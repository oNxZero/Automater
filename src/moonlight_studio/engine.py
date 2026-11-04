"""Interruptible replay with a monotonic clock, independent of the GUI loop."""

import threading
import time
from dataclasses import dataclass

from .models import Script, Step, number


@dataclass(frozen=True)
class PlaybackOptions:
    speed: float = 1.0
    repeats: int = 1
    countdown: float = 3.0
    loop_gap: float = 0.25

    def __post_init__(self):
        number(self.speed, "Speed", 0.1, 10)
        number(self.countdown, "Countdown", 0, 30)
        number(self.loop_gap, "Loop gap", 0, 3600)
        if type(self.repeats) is not int or not 0 <= self.repeats <= 100_000:
            raise ValueError("Repeat count must be 0 (until stopped) through 100,000")


class Replay:
    def __init__(self, backend_factory, notify=lambda *args: None):
        self.backend_factory = backend_factory
        self.notify = notify
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
        snapshot = Script(script.name, script.notes, list(script.steps), script.version)
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
                    for code in sorted(held):
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
        for code in sorted(held):
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
            self.notify("state", f"Starting in {options.countdown:g}s…")
            # Targets need only be focused when the countdown finishes.
            deadline = self._wait(time.monotonic() + options.countdown, _NoCheck(), held)
            if deadline is None:
                return
            backend.check()
            self.notify("state", "Playing")
            loop = 0
            last_progress = 0.0
            while not self._stop and (options.repeats == 0 or loop < options.repeats):
                loop += 1
                for index, step in enumerate(script.steps):
                    if not step.enabled:
                        continue
                    deadline = self._wait(
                        deadline + step.delay_ms / 1000 / options.speed, backend, held
                    )
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

    def check(self):
        pass

    def send(self, step):
        pass

    def close(self):
        pass
