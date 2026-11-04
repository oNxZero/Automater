"""A continuous, critically damped camera: retargeting retains its velocity."""

import math
import time

from PySide6.QtCore import QObject, QPointF, Qt, QTimer, Signal


class CameraFollower(QObject):
    positionChanged = Signal(QPointF)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.position = QPointF()
        self.target = QPointF()
        self.velocity = QPointF()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(8)
        self.timer.timeout.connect(self.tick)
        self.last_tick = 0.0

    def move_to(self, current, target):
        if not self.timer.isActive():
            self.position = QPointF(current)
            self.velocity = QPointF()
            self.last_tick = time.monotonic()
            self.timer.start()
        self.target = QPointF(target)

    def tick(self):
        now = time.monotonic()
        self.advance(min(0.05, max(0, now - self.last_tick)))
        self.last_tick = now

    def advance(self, seconds):
        omega = 14.0
        decay = math.exp(-omega * seconds)
        before = QPointF(self.position)
        difference = self.position - self.target
        coefficient = self.velocity + difference * omega
        self.position = self.target + (difference + coefficient * seconds) * decay
        self.velocity = (self.velocity - coefficient * (omega * seconds)) * decay
        # A retarget near a scroll boundary can leave too much inherited velocity.
        # Stop on each target axis instead of overshooting and bouncing back.
        for axis in ("x", "y"):
            previous = getattr(before, axis)() - getattr(self.target, axis)()
            current = getattr(self.position, axis)() - getattr(self.target, axis)()
            if previous == 0 or previous * current < 0:
                getattr(self.position, "set" + axis.upper())(getattr(self.target, axis)())
                getattr(self.velocity, "set" + axis.upper())(0)
        if (
            self.position - self.target
        ).manhattanLength() < 0.25 and self.velocity.manhattanLength() < 0.5:
            self.position = QPointF(self.target)
            self.stop()
        self.positionChanged.emit(self.position)

    def stop(self):
        self.timer.stop()
        self.velocity = QPointF()
