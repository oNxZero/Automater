"""Playback-colored connections, animated only while a transition is active."""

import time
from bisect import bisect_right

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QGraphicsPathItem

from .run_feedback import block_state
from .theme import paint_color

COLORS = {
    "": "#5d5877",
    "completed": "#75d6c0",
    "running": "#b5a4fa",
    "last": "#83b8f2",
    "stopped": "#e8c58a",
    "failed": "#f2a3bc",
    "paused": "#a69a80",
}


def connection_state(boundary, blocks, starts, trace):
    if (
        not trace
        or not blocks
        or trace["phase"] in ("preparing", "countdown", "activating", "positioning", "settling")
    ):
        return ""
    if boundary == len(blocks):
        if (
            trace["phase"] in ("finished", "loop_gap")
            and trace["completed_events"] == trace["enabled_events"]
            and trace["enabled_events"]
        ):
            return (
                "completed"
                if trace["outcome"] == "finished" or trace["phase"] == "loop_gap"
                else "failed"
                if trace["outcome"] == "failed"
                else "stopped"
            )
        return ""
    state = block_state(blocks[boundary], trace)
    if trace["phase"] == "paused":
        row = max(trace.get("last_sent_row", -1), trace.get("active_row", -1))
        return "paused" if row >= 0 and boundary == bisect_right(starts, row) - 1 else state
    if state in ("running", "completed", "last", "stopped", "failed"):
        return state
    if trace["phase"] == "delay" and trace.get("next_row", -1) >= 0:
        upcoming = bisect_right(starts, trace["next_row"]) - 1
        if boundary == upcoming and blocks[boundary].enabled:
            return "running"  # Flow towards the next input; its card is still waiting.
    return ""


class FlowConnection(QGraphicsPathItem):
    def __init__(self, path, arrow):
        super().__init__(path)
        self.arrow = arrow
        self.state = ""
        self.setPen(QPen(paint_color(COLORS[""]), 2))
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setZValue(-3)

    def boundingRect(self):
        return self.path().boundingRect().united(self.arrow.boundingRect()).adjusted(-7, -7, 7, 7)

    def set_state(self, state):
        if state != self.state:
            self.state = state
            self.setPen(QPen(paint_color(COLORS[state]), 2))
            self.update()

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        color = paint_color(COLORS[self.state])
        painter.setPen(QPen(color, 2.2 if self.state else 1.5))
        painter.drawPath(self.path())
        painter.drawPath(self.arrow)
        if self.state == "running":
            pen = QPen(paint_color("#eee6ff"), 2.5, Qt.CustomDashLine)
            pen.setDashPattern([3, 7])
            pen.setDashOffset((-time.monotonic() * 18) % 10)
            painter.setPen(pen)
            painter.drawPath(self.path())
            point = self.path().pointAtPercent((time.monotonic() * 0.65) % 1)
            painter.setPen(Qt.NoPen)
            painter.setBrush(paint_color("#eee6ff"))
            painter.drawEllipse(point, 2.8, 2.8)
