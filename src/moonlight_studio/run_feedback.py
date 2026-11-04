"""Playback presentation uses the worker's clock and completed events."""

import time

from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import QMessageBox


def block_state(block, trace):
    if block.kind == "note":
        return ""
    final = trace["phase"] == "finished"
    completed = trace["completed_row"]
    failed = trace["failed_row"]
    last = trace["last_activity_row"]
    active = set(trace.get("held_rows", ())) | {trace["active_row"]}
    if trace["phase"] in (
        "paused",
        "preparing",
        "countdown",
        "positioning",
        "settling",
        "loop_gap",
    ):
        active.clear()
    state = "completed" if block.enabled and block.end - 1 <= completed else ""
    if not final and any(block.start <= row < block.end for row in active):
        state = "running"
    if (
        not final
        and trace["phase"] == "delay"
        and block.kind in ("move", "scroll")
        and block.start <= completed < block.end - 1
        and block.start <= trace.get("next_row", -1) < block.end
    ):
        state = "running"
    if final and block.start <= last < block.end:
        state = "last" if block.enabled and block.end - 1 <= completed else "stopped"
    if final and block.start <= failed < block.end:
        state = "failed"
    return state


def block_states(blocks, steps, trace):
    return {index: block_state(block, trace) for index, block in enumerate(blocks)} if trace else {}


class RunFeedbackMixin:
    def clear_run_feedback(self, force=False):
        if self.busy and not force:
            return
        self.last_run = None
        self.model.clear_execution()
        self.workflow.canvas.set_execution({})
        self.workflow.run_summary.hide()
        self.model.highlight(-1)

    def render_playback(self, trace=None):
        if trace is None:
            replay = getattr(self, "replay", None)
            trace = replay.timeline if replay is not None else None
        if not trace:
            return
        self.last_run = dict(trace)
        phase = trace["phase"]
        final = phase == "finished"
        self.workflow.canvas.set_execution_trace(trace)
        self.model.set_execution(trace)
        row = trace["active_row"] if not final and phase != "paused" else -1
        self.model.highlight(row)
        duration = trace.get("wait_duration", 0)
        remaining = (
            max(0, trace["deadline"] - time.monotonic()) if trace.get("deadline") is not None else 0
        )
        elapsed = trace.get("loop_elapsed", 0)
        if phase in ("delay", "timer"):
            elapsed += max(0, min(duration, duration - remaining))
        elif phase == "paused":
            elapsed += trace.get("paused_wait_elapsed", 0)
        elif final:
            elapsed += trace.get("partial_wait_seconds", 0)
        total = trace.get("loop_duration", 0)
        fraction = (
            elapsed / total
            if total
            else trace["completed_events"] / max(1, trace["enabled_events"])
        )
        self.progress.setValue(round(max(0, min(1, fraction)) * 1000))
        self.playback_deadline = trace["deadline"] if phase == "countdown" else None
        if phase == "countdown":
            self.countdown_total = duration
            self.update_countdown()
        else:
            self.countdown_banner.hide()
        self.playback_started = phase not in ("preparing", "countdown", "finished")
        self.pause_btn.setVisible(not final and self.playback_started)
        self.pause_btn.setText("Resume · F8" if phase == "paused" else "Pause · F8")
        labels = {
            "preparing": "Preparing destination",
            "activating": "Bringing the selected window forward",
            "countdown": f"Starting in {remaining:.1f}s",
            "positioning": "Resetting game cursor",
            "settling": f"Cursor settling · {remaining:.2f}s",
            "loop_gap": f"Between loops · {remaining:.2f}s",
            "paused": "Paused · held inputs released",
            "finished": trace["outcome"].capitalize(),
        }
        text = labels.get(
            phase,
            f"{remaining:.2f}s until next input"
            if phase == "delay"
            else f"{remaining:.2f}s remaining"
            if phase == "timer"
            else "Sending input",
        )
        prefix = "Test mode" if self.test_mode.isChecked() else "Playback"
        if phase == "countdown":
            self.run_state.setText("●  STARTING")
        elif phase == "paused":
            self.run_state.setText("Ⅱ  PAUSED")
        elif not final:
            self.run_state.setText("●  PREVIEW" if self.test_mode.isChecked() else "●  RUNNING")
        if final:
            self.workflow.run_summary.setText(
                f"Last run · loop {trace['loop']} · {trace['completed_events']}/{trace['enabled_events']} events completed · "
                + (
                    f"failed at event {trace['failed_row'] + 1}"
                    if trace["failed_row"] >= 0
                    else f"last action at event {trace['last_activity_row'] + 1}"
                    if trace["last_activity_row"] >= 0
                    else "no action started"
                )
                + " · completed, last, stopped and failed actions stay marked"
            )
            self.workflow.run_summary.show()
            QTimer.singleShot(
                0,
                self,
                lambda: (
                    self.workflow.canvas.set_execution_trace(trace)
                    if self.last_run == trace and not self.busy
                    else None
                ),
            )
        elif not getattr(self, "playback_error", False):
            self.status.setText(f"{prefix} · loop {trace['loop']} · {text}")
        self.status.setToolTip(
            (trace.get("error", "") + "\n" if trace.get("error") else "")
            + f"Requested schedule; maximum measured dispatch lateness: {trace['max_lateness_ms']:.2f} ms. This does not measure game receipt or camera movement."
        )

    @Slot()
    def show_run_details(self):
        if not self.last_run:
            return
        trace = self.last_run
        QMessageBox.information(
            self,
            "Last playback details",
            f"Result: {trace['outcome']}\nLoop: {trace['loop']}\n"
            f"Completed events this loop: {trace['completed_events']}/{trace['enabled_events']}\n"
            f"Last successful event: {trace['last_sent_row'] + 1 or 'none'}\n"
            f"Failed event: {trace['failed_row'] + 1 or 'none'}\n"
            f"Maximum dispatch lateness: {trace['max_lateness_ms']:.2f} ms\n"
            f"Requested event timing this loop: {trace['loop_duration']:.3f} s\n"
            f"Actual loop (excluding pauses, reset and gap): {trace.get('actual_loop_seconds', 0):.3f} s\n"
            f"Error: {trace['error'] or 'none'}\n\n"
            "Times measure the local scheduler and backend, not receipt by the game. "
            "Mouse counts are preserved; acceleration, sensitivity and game state affect the path.",
        )
