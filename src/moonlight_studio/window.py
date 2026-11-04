import time
from bisect import bisect_right
from dataclasses import replace
from functools import partial
from pathlib import Path

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QCursor, QKeySequence, QUndoStack
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
)

from . import storage, x11
from .designer import build_ui
from .editor import StepModel
from .engine import DryRun, PlaybackOptions, Replay
from .linux_input import DeviceMonitor, Recorder, UInputBackend, devices, diagnostics
from .models import Script, Step
from .theme import STYLE, icon
from .workflow import blocks_for


class Bridge(QObject):
    replay = Signal(str, object)
    hotkey = Signal(str)
    monitor_error = Signal(str)


def sample():
    return Script(
        "Movement + interaction",
        "Example: hold W, pause, then tap E. Test mode emits no input.",
        [
            Step(0, "key_down", "KEY_W"),
            Step(650, "key_up", "KEY_W"),
            Step(250, "wait"),
            Step(0, "key_down", "KEY_E"),
            Step(60, "key_up", "KEY_E"),
        ],
    )


class MainWindow(QMainWindow):
    def __init__(self, config_dir=None, demo=False):
        super().__init__()
        self.config_dir = Path(config_dir) if config_dir else storage.data_dir()
        self.library_dir = self.config_dir / "scripts"
        self.recovery_path = self.config_dir / "recovery.json"
        self.path = None
        self.saved_snapshot = Script().to_dict()
        self.loading = False
        self.busy = False
        self.record_pending = False
        self.monitor = None
        self.monitor_ok = False
        self.recorder = Recorder()
        self.bridge = Bridge()
        self.bridge.replay.connect(self.on_replay)
        self.bridge.hotkey.connect(self.on_hotkey)
        self.bridge.monitor_error.connect(self.on_monitor_error)
        self.undo = QUndoStack(self)
        self.undo.setUndoLimit(50)
        self.model = StepModel(self.undo)
        self.model.invalid.connect(self.show_error)
        self.selection_anchor = -1
        self.active_block = None
        self._sync_selection = False
        self.blocks = []
        self.setWindowIcon(icon("moon", "#b5a4fa"))
        self.setWindowTitle("Moonlight Studio")
        self.resize(1480, 900)
        self.setMinimumSize(1100, 740)
        self.setStyleSheet(STYLE)
        self.build_ui()
        self.model.changed.connect(self.edited)
        self.model.changed.connect(self.refresh_workflow)
        self.name.textChanged.connect(self.edited)
        self.notes.textChanged.connect(self.edited)
        self.add_shortcuts()
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(5000)
        self.autosave_timer.timeout.connect(self.autosave)
        self.autosave_timer.start()
        self.capture_timer = QTimer(self)
        self.capture_timer.setInterval(100)
        self.capture_timer.timeout.connect(self.capture_tick)
        self.capture_timer.start()
        self.record_timer = QTimer(self)
        self.record_timer.setInterval(100)
        self.record_timer.timeout.connect(self.record_tick)
        self.load_script(sample() if demo else Script())
        if demo:
            self.test_mode.setChecked(True)
        self.refresh_library()
        self.refresh_devices()
        self.refresh_windows()
        if not demo:
            QTimer.singleShot(0, self.offer_recovery)

    def build_ui(self):
        build_ui(self)

    @Slot(bool)
    def update_undo_actions(self, _enabled=False):
        self.undo_btn.setEnabled(not self.busy and self.undo.canUndo())
        self.redo_btn.setEnabled(not self.busy and self.undo.canRedo())

    def add_shortcuts(self):
        for key, callback in (
            ("Ctrl+N", self.new_script),
            ("Ctrl+O", self.open_script),
            ("Ctrl+S", self.save_script),
            ("Ctrl+Shift+S", self.save_as),
            ("Ctrl+Z", self.undo.undo),
            ("Ctrl+Shift+Z", self.undo.redo),
        ):
            action = QAction(self)
            action.setShortcut(QKeySequence(key))
            action.triggered.connect(
                lambda checked=False, cb=callback: cb() if not self.busy else None
            )
            self.addAction(action)
        # Global F-key controls come only from evdev. Qt bindings would double-fire.

    def script(self):
        return Script(
            self.name.text().strip(), self.notes.toPlainText(), list(self.model.steps)
        ).validate()

    def dirty(self):
        try:
            return self.script().to_dict() != self.saved_snapshot
        except ValueError:
            return True

    def edited(self):
        if self.loading:
            return
        self.update_stats()
        title = self.name.text().strip() or "Untitled script"
        self.setWindowTitle(f"{'● ' if self.dirty() else ''}{title} — Moonlight Studio")
        self.saved_badge.setText(
            "Unsaved changes" if self.dirty() else "Saved" if self.path else "Local workflow"
        )
        self.update_run_summary()

    def update_stats(self):
        duration = sum(s.delay_ms for s in self.model.steps if s.enabled) / 1000
        self.stats.setText(
            f"{len(self.blocks):,} actions   ·   {len(self.model.steps):,} original events   ·   {duration:.2f} s at 1×"
        )

    def navigate(self, page, view=0):
        if self.busy and page != 0:
            return
        self.pages.setCurrentIndex(page)
        if page == 0:
            self.inspector_panel.setVisible(bool(self.model.steps) or view == 1)
            self.editor_stack.setCurrentIndex(2 if not self.model.steps and view == 0 else view)
            self.flow_btn.setChecked(view == 0)
            self.events_btn.setChecked(view == 1)
        self.nav_buttons[view if page == 0 else page + 1].setChecked(True)
        self.settings_btn.setVisible(page == 0)

    def show_inspector(self, index):
        self.navigate(0, 1 if self.events_btn.isChecked() else 0)
        self.inspector_panel.show()
        self.inspector_stack.setCurrentIndex(index)
        self.inspector_buttons[index].setChecked(True)

    def update_run_summary(self):
        if not hasattr(self, "transport_hint"):
            return
        self.transport_hint.setText(
            "Preview only · no input sent"
            if self.test_mode.isChecked()
            else "Background window"
            if self.mode.currentIndex()
            else "Active desktop"
        )
        cycle = sum(s.delay_ms for s in self.model.steps if s.enabled) / self.speed.value() / 1000
        count = self.repeats.value()
        estimate = f"{cycle:.2f} s per cycle"
        if count:
            total = (
                self.countdown.value()
                + cycle * count
                + max(0.01, self.gap.value()) * max(0, count - 1)
            )
            estimate += f" · {total:.2f} s total"
        else:
            estimate += " · repeats until stopped"
        self.run_estimate.setText(estimate)

    def filter_library(self):
        query = self.library_search.text().strip().lower()
        visible = 0
        for i in range(self.library.count()):
            item = self.library.item(i)
            item.setHidden(query not in item.text().lower())
            visible += not item.isHidden()
        self.library_empty.setVisible(visible == 0)
        self.library_empty.setText(
            f"No workflows match “{self.library_search.text()}”."
            if query
            else "No saved workflows yet. Use Save workflow to add your first one."
        )

    def refresh_workflow(self):
        self.blocks = blocks_for(self.model.steps)
        row = min(self.selection_anchor, len(self.model.steps) - 1)
        self.workflow.canvas.rebuild(self.blocks, row)
        self.workflow.update_footer()
        self.update_stats()
        if self.blocks and row >= 0:
            index = max(0, bisect_right(self.workflow.canvas.starts, row) - 1)
            self.select_block(self.blocks[index])
        else:
            self.active_block = None
            self.action_inspector.select(None, self.model.steps)
        if self.pages.currentIndex() == 0:
            self.navigate(0, 1 if self.events_btn.isChecked() else 0)

    def select_block(self, block):
        if self._sync_selection or self.busy:
            return
        self.active_block = block
        self.action_inspector.select(block, self.model.steps)
        self._sync_selection = True
        self.table.clearSelection()
        if block is not None:
            self.selection_anchor = block.start
            selected = QItemSelection(
                self.model.index(block.start, 0), self.model.index(block.end - 1, 5)
            )
            self.table.selectionModel().select(
                selected, QItemSelectionModel.Select | QItemSelectionModel.Rows
            )
            self.workflow.canvas.select_row(block.start, reveal=False)
            self.show_inspector(0)
        else:
            self.selection_anchor = -1
        self._sync_selection = False

    def table_selection_changed(self, *args):
        if self._sync_selection or self.busy:
            return
        rows = self.selected_rows()
        if not rows or not self.blocks:
            return
        row = rows[0]
        self.selection_anchor = row
        index = max(0, bisect_right(self.workflow.canvas.starts, row) - 1)
        self.active_block = self.blocks[index]
        self.action_inspector.select(self.active_block, self.model.steps)
        self.workflow.canvas.select_row(row)
        self.workflow.update_footer()

    def choose_action(self, row=None):
        if self.busy:
            return
        # clicked(bool) is distinct from a canvas insertion row.
        row = row if type(row) is int else None
        menu = QMenu(self)
        for kind, (title, glyph) in enumerate(
            (
                ("Keyboard press", "key"),
                ("Mouse click", "mouse"),
                ("Wait", "wait"),
                ("Move pointer", "move"),
                ("Scroll", "scroll"),
            )
        ):
            item = menu.addAction(icon(glyph), title)
            item.triggered.connect(lambda checked=False, k=kind, r=row: self.add_step(k, r))
        menu.exec(QCursor.pos())

    def apply_block(self, block, values):
        if self.busy or block not in self.blocks:
            return
        try:
            subset = list(self.model.steps[block.start : block.end])
            original_duration = sum(s.delay_ms for s in subset[1:])
            for i, step in enumerate(subset):
                edits = {"enabled": values["enabled"]}
                if i == 0:
                    edits["delay_ms"] = values["delay"]
                elif len(subset) == 2:
                    edits["delay_ms"] = values["duration"]
                elif original_duration:
                    edits["delay_ms"] = step.delay_ms * values["duration"] / original_duration
                else:
                    edits["delay_ms"] = values["duration"] / (len(subset) - 1)
                if block.kind in ("key", "mouse"):
                    edits["code"] = values["code"]
                elif block.kind in ("move", "scroll") and len(subset) == 1:
                    edits.update(x=values["x"], y=values["y"])
                subset[i] = replace(step, **edits)
            self.selection_anchor = block.start
            self.model.commit(
                self.model.steps[: block.start] + subset + self.model.steps[block.end :],
                "Edit action",
            )
            self.status.setText("Action updated · Undo is available")
        except (ValueError, TypeError) as exc:
            self.show_error(str(exc))

    def reorder_blocks(self, source, target):
        if (
            self.busy
            or source == target
            or not 0 <= source < len(self.blocks)
            or not 0 <= target < len(self.blocks)
        ):
            return
        block, other = self.blocks[source], self.blocks[target]
        steps = list(self.model.steps)
        moving = steps[block.start : block.end]
        del steps[block.start : block.end]
        destination = other.end - len(moving) if target > source else other.start
        steps[destination:destination] = moving
        self.selection_anchor = destination
        self.model.commit(steps, "Reorder action")

    def workflow_command(self, command):
        if self.busy or not self.active_block:
            return
        block = self.active_block
        index = self.blocks.index(block)
        if command == "duplicate":
            self.select_block(block)
            self.duplicate()
        elif command == "delete":
            self.select_block(block)
            self.delete()
        elif command == "toggle":
            steps = list(self.model.steps)
            steps[block.start : block.end] = [
                replace(s, enabled=not block.enabled) for s in steps[block.start : block.end]
            ]
            self.model.commit(steps, "Toggle action")
        elif command in ("left", "right"):
            self.reorder_blocks(index, index + (-1 if command == "left" else 1))
        elif command in ("select_left", "select_right"):
            target = index + (-1 if command == "select_left" else 1)
            if 0 <= target < len(self.blocks):
                self.select_block(self.blocks[target])
                self.workflow.canvas.select_row(self.blocks[target].start)

    def load_script(self, script, path=None):
        self.loading = True
        self.path = Path(path) if path else None
        self.selection_anchor = 0 if script.steps else -1
        self.name.setText(script.name)
        self.notes.setPlainText(script.notes)
        self.model.replace(script.steps)
        self.undo.clear()
        self.saved_snapshot = script.to_dict()
        self.loading = False
        self.edited()
        self.navigate(0, 0)
        QTimer.singleShot(0, self.workflow.canvas.fit)

    def confirm_discard(self):
        if self.busy:
            return False
        if not self.dirty():
            return True
        result = QMessageBox.question(
            self,
            "Unsaved changes",
            "Save changes before continuing?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        )
        if result == QMessageBox.Save:
            return self.save_script()
        if result == QMessageBox.Discard:
            self.clear_recovery()
            return True
        return False

    def clear_recovery(self):
        try:
            self.recovery_path.unlink(missing_ok=True)
        except OSError as exc:
            self.show_error(f"Could not clear recovery file: {exc}")

    def new_script(self):
        if self.confirm_discard():
            self.load_script(Script())

    def load_example(self):
        if self.confirm_discard():
            self.load_script(sample())
            self.test_mode.setChecked(True)
            self.status.setText("Example loaded • test mode is on")

    def open_script(self):
        if not self.confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open script", str(self.library_dir), "Scripts (*.json)"
        )
        if path:
            self.open_path(path)

    def open_path(self, path):
        try:
            script = storage.load(path)
            self.load_script(script, path)
            self.status.setText(f"Opened {Path(path).name}")
        except (ValueError, OSError) as exc:
            self.show_error(str(exc))

    def save_script(self):
        if self.busy:
            return False
        if self.path is None:
            return self.save_as()
        try:
            script = self.script()
            storage.save(script, self.path)
            self.saved_snapshot = script.to_dict()
            self.clear_recovery()
            self.edited()
            self.refresh_library()
            self.status.setText(f"Saved {self.path.name}")
            return True
        except (ValueError, OSError) as exc:
            self.show_error(str(exc))
            return False

    def save_as(self):
        if self.busy:
            return False
        default = "".join(c if c.isalnum() or c in " -_" else "_" for c in self.name.text())
        dialog = QFileDialog(
            self, "Save script", str(self.library_dir / (default + ".json")), "Scripts (*.json)"
        )
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        dialog.setDefaultSuffix("json")
        if dialog.exec() != QDialog.Accepted:
            return False
        old = self.path
        self.path = Path(dialog.selectedFiles()[0])
        if self.save_script():
            return True
        self.path = old
        return False

    def refresh_library(self):
        self.library.clear()
        for path in sorted(self.library_dir.glob("*.json")):
            item = QListWidgetItem(path.stem)
            item.setIcon(icon("flow", "#b5a4fa"))
            item.setData(Qt.UserRole, str(path))
            item.setToolTip(str(path))
            self.library.addItem(item)
        self.library_empty.setVisible(self.library.count() == 0)
        self.filter_library()

    def open_library(self, item):
        path = item.data(Qt.UserRole)
        if self.confirm_discard():
            self.open_path(path)

    def autosave(self):
        if self.loading or self.busy or not self.dirty():
            return
        try:
            storage.save(self.script(), self.recovery_path)
        except (OSError, ValueError) as exc:
            self.status.setText(f"Autosave unavailable: {exc}")

    def offer_recovery(self):
        if self.recovery_path.exists():
            try:
                recovered = storage.load(self.recovery_path)
                if (
                    QMessageBox.question(self, "Recover work", "Restore the last autosaved script?")
                    == QMessageBox.Yes
                ):
                    self.load_script(recovered)
                    self.saved_snapshot = Script().to_dict()
                    self.edited()
            except (ValueError, OSError) as exc:
                self.show_error(f"Could not recover autosave: {exc}")

    def selected_rows(self):
        return sorted({i.row() for i in self.table.selectionModel().selectedRows()})

    def add_step(self, kind=0, row=None):
        if self.busy:
            return
        choices = [
            [Step(100, "key_down", "KEY_SPACE"), Step(60, "key_up", "KEY_SPACE")],
            [Step(100, "key_down", "BTN_LEFT"), Step(60, "key_up", "BTN_LEFT")],
            [Step(250, "wait")],
            [Step(16, "move", x=10)],
            [Step(100, "scroll", y=1)],
        ]
        rows = self.selected_rows()
        at = row if row is not None else rows[-1] + 1 if rows else len(self.model.steps)
        self.selection_anchor = at
        self.model.commit(
            self.model.steps[:at] + choices[kind] + self.model.steps[at:], "Add steps"
        )
        self.workflow.canvas.select_row(at)
        self.navigate(0, 1 if self.events_btn.isChecked() else 0)

    def duplicate(self):
        rows = self.selected_rows()
        if rows:
            at = rows[-1] + 1
            self.model.commit(
                self.model.steps[:at] + [self.model.steps[i] for i in rows] + self.model.steps[at:],
                "Duplicate steps",
            )

    def delete(self):
        rows = set(self.selected_rows())
        self.model.commit(
            [s for i, s in enumerate(self.model.steps) if i not in rows], "Delete steps"
        )

    def move(self, direction):
        rows = self.selected_rows()
        if not rows or rows != list(range(rows[0], rows[-1] + 1)):
            self.status.setText("Select a consecutive group of steps to move")
            return
        if rows[0] + direction < 0 or rows[-1] + direction >= len(self.model.steps):
            return
        steps = list(self.model.steps)
        if direction < 0:
            item = steps.pop(rows[0] - 1)
            steps.insert(rows[-1], item)
        else:
            item = steps.pop(rows[-1] + 1)
            steps.insert(rows[0], item)
        self.model.commit(steps, "Move steps")
        self.table.selectRow(rows[0] + direction)

    def update_busy(self, busy):
        self.busy = busy
        for widget in (
            self.edit_workspace,
            self.name,
            self.new_btn,
            self.open_btn,
            self.save_btn,
            self.save_as_btn,
            self.add_btn,
            self.action_inspector,
            self.device_list,
            self.mode,
            self.target,
            self.refresh_target_btn,
            self.speed,
            self.repeats,
            self.countdown,
            self.gap,
            self.test_mode,
            self.capture_keys,
            self.capture_buttons,
            self.capture_motion,
        ):
            widget.setEnabled(not busy)
        self.play_btn.setEnabled(not self.recorder.active and not self.record_pending)
        self.record_btn.setEnabled(not busy or self.recorder.active or self.record_pending)
        self.pause_btn.setEnabled(bool(getattr(self, "replay", None) and self.replay.running))
        self.stop_btn.setEnabled(busy)
        for nav in self.nav_buttons[2:]:
            nav.setEnabled(not busy)
        self.undo_btn.setEnabled(not busy and self.undo.canUndo())
        self.redo_btn.setEnabled(not busy and self.undo.canRedo())
        self.empty_record.setEnabled(not busy)
        if not busy:
            self.run_state.setText("●  READY")
        self.update_run_summary()
        if not busy:
            self.routing_changed()

    def routing_changed(self):
        background = self.mode.currentIndex() == 1
        self.target.setEnabled(background and not self.busy)
        self.refresh_target_btn.setEnabled(background and not self.busy)
        self.target.setVisible(background)
        self.refresh_target_btn.setVisible(background)
        self.routing_hint.setText(
            "Sends to one X11/Xwayland window without taking focus. Games may ignore it. "
            "Mouse movement is a virtual cursor starting at the window center."
            if background
            else "Sends to the active desktop. Focus the game during the countdown. "
            "Works on Wayland and X11 with uinput access."
        )
        self.update_run_summary()

    def refresh_windows(self):
        self.target.clear()
        self.target.addItem("Choose a program window…", None)
        try:
            for window in x11.windows():
                self.target.addItem(f"{window.title} · PID {window.pid}", window)
        except Exception as exc:
            self.target.setToolTip(f"X11 window enumeration unavailable: {exc}")

    def refresh_devices(self):
        if self.busy:
            return
        previous = {
            self.device_list.item(i).data(Qt.UserRole): self.device_list.item(i).checkState()
            for i in range(self.device_list.count())
        }
        if self.monitor:
            self.monitor.stop()
        self.monitor_ok = False
        self.device_list.clear()
        try:
            found = devices()
            for device in found:
                item = QListWidgetItem(device.name)
                item.setData(Qt.UserRole, device.path)
                item.setToolTip(device.path)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(
                    previous.get(device.path, Qt.Checked) if device.readable else Qt.Unchecked
                )
                if not device.readable:
                    item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                self.device_list.addItem(item)
            paths = [
                self.device_list.item(i).data(Qt.UserRole)
                for i in range(self.device_list.count())
                if self.device_list.item(i).checkState() == Qt.Checked
            ]
            info = diagnostics()
            self.health.setText(
                f"Session: {info['session']}\nReadable devices: {info['readable_devices']}\n"
                f"uinput: {'ready' if info['uinput_writable'] else 'permission / module needed'}"
            )
            if paths:
                self.monitor = DeviceMonitor(
                    paths, self.recorder, self.bridge.hotkey.emit, self.bridge.monitor_error.emit
                )
                self.monitor_ok = True
                self.monitor.start()
                self.notice.setText(
                    "Input monitor ready. Record a routine or build your own workflow."
                )
                self.device_badge.setText("Input monitor ready")
                self.setup_link.setVisible(False)
            else:
                self.notice.setText(
                    "Try your workflow in Test mode. Set up input access when you're ready to record."
                )
                self.device_badge.setText("Input setup needed")
                self.setup_link.setVisible(True)
        except Exception as exc:
            self.notice.setText(f"Input setup unavailable: {exc}")

    def on_monitor_error(self, text):
        self.monitor_ok = False
        if self.busy:
            self.stop()
        self.show_error(
            f"Input monitor stopped: {text} • Reconnect devices, then Apply / refresh in Setup."
        )

    def on_hotkey(self, action):
        if action != "stop" and QApplication.activeModalWidget() is not None:
            return
        if action == "stop":
            self.stop()
        elif action == "record":
            self.toggle_record()
        elif action == "play":
            self.toggle_play()
        elif action == "pause":
            self.pause()

    def toggle_record(self):
        if self.recorder.active or self.record_pending:
            self.stop()
            return
        if self.busy:
            return
        if not any(
            w.isChecked() for w in (self.capture_keys, self.capture_buttons, self.capture_motion)
        ):
            self.show_error("Select at least one input category to record")
            return
        self.refresh_devices()
        if not self.monitor_ok:
            self.navigate(2)
            self.show_error("No selected readable input devices. Open Permissions & help in Setup.")
            return
        self.record_pending = True
        self.navigate(0, 0)
        self.record_deadline = time.monotonic() + self.countdown.value()
        self.record_btn.setText("Finish recording  ·  F6")
        self.update_busy(True)
        self.record_timer.start()
        self.record_tick()

    def record_tick(self):
        if not self.record_pending:
            return
        remaining = self.record_deadline - time.monotonic()
        if remaining > 0:
            self.run_state.setText("●  STARTING")
            self.status.setText(f"Recording starts in {remaining:.1f}s • F12 cancels")
            return
        self.record_timer.stop()
        self.record_pending = False
        self.recorder.start(
            self.capture_keys.isChecked(),
            self.capture_buttons.isChecked(),
            self.capture_motion.isChecked(),
        )
        self.record_started = time.monotonic()
        self.update_busy(True)

    def capture_tick(self):
        if self.recorder.active:
            self.run_state.setText("●  RECORDING")
            self.status.setText(
                f"● Recording  ·  {time.monotonic() - self.record_started:.1f}s  ·  "
                f"{self.recorder.count():,} events  ·  F6 finish / F12 stop"
            )

    def toggle_play(self):
        if getattr(self, "replay", None) and self.replay.running:
            self.stop()
            return
        if self.busy:
            return
        try:
            script = self.script()
            if not self.test_mode.isChecked() and script.warnings():
                response = QMessageBox.question(
                    self,
                    "Review input sequence",
                    "\n".join(script.warnings()[:8]) + "\n\nContinue with automatic cleanup?",
                )
                if response != QMessageBox.Yes:
                    return
            if self.test_mode.isChecked():
                factory = DryRun
            elif self.mode.currentIndex() == 1:
                target = self.target.currentData()
                if target is None:
                    raise ValueError("Choose a target program window first")
                factory = partial(x11.BackgroundBackend, target)
            else:
                factory = UInputBackend
            self.playback_error = False
            self.playback_stopped = False
            self.navigate(0, 1 if self.events_btn.isChecked() else 0)
            self.replay = Replay(factory, self.bridge.replay.emit)
            self.replay.start(
                script,
                PlaybackOptions(
                    self.speed.value(),
                    self.repeats.value(),
                    self.countdown.value(),
                    self.gap.value(),
                ),
            )
            self.play_btn.setText("Stop run  ·  F7")
            self.play_btn.setIcon(icon("stop", "#211b30"))
            self.progress.setValue(0)
            self.update_busy(True)
        except (ValueError, RuntimeError) as exc:
            self.show_error(str(exc))

    def pause(self):
        if getattr(self, "replay", None) and self.replay.running:
            self.replay.pause()

    def stop(self):
        if self.record_pending:
            self.record_pending = False
            self.record_timer.stop()
            self.status.setText("Recording cancelled")
        if self.recorder.active:
            steps = self.recorder.stop()
            self.selection_anchor = 0 if steps else -1
            self.model.commit(steps, "Replace with recording")
            self.status.setText(
                f"Recording finished • {len(steps):,} steps • Undo restores previous steps"
            )
        self.record_btn.setText("●  Record  ·  F6")
        if getattr(self, "replay", None) and self.replay.running:
            self.playback_stopped = True
            self.replay.stop()
            self.status.setText("Stopping • releasing held inputs…")
        else:
            self.update_busy(False)
            self.autosave()

    def on_replay(self, event, value):
        if event == "state":
            prefix = "Test mode · " if self.test_mode.isChecked() else ""
            self.status.setText(prefix + value)
            self.run_state.setText(
                "Ⅱ  PAUSED"
                if value.startswith("Paused")
                else "●  PREVIEW"
                if self.test_mode.isChecked()
                else "●  RUNNING"
            )
        elif event == "progress":
            row, loop = value
            self.model.highlight(row)
            self.workflow.canvas.highlight(row)
            self.workflow.update_footer()
            self.progress.setValue(round((row + 1) / max(1, len(self.model.steps)) * 1000))
            self.run_state.setText("●  PREVIEW" if self.test_mode.isChecked() else "●  RUNNING")
            self.table.scrollTo(self.model.index(row, 0))
            self.status.setText(
                f"{'Test mode' if self.test_mode.isChecked() else 'Playing'} · "
                f"loop {loop} · step {row + 1:,}/{len(self.model.steps):,}"
            )
        elif event == "error":
            self.playback_error = True
            self.show_error(value)
        elif event == "finished":
            self.model.highlight(-1)
            self.workflow.canvas.highlight(-1)
            self.run_state.setText("●  READY")
            self.play_btn.setText("Run workflow  ·  F7")
            self.play_btn.setIcon(icon("play", "#211b30"))
            self.update_busy(False)
            if not self.playback_error:
                self.status.setText(
                    "Playback stopped • held inputs released"
                    if self.playback_stopped
                    else "Playback finished • held inputs released"
                )
                if not self.playback_stopped:
                    self.progress.setValue(1000)

    def show_error(self, text):
        self.status.setText("⚠  " + text)
        self.status.setToolTip(text)

    def show_help(self):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Linux input setup")
        dialog.setText(
            "Moonlight Studio needs read access to selected /dev/input/event* devices "
            "and write access to /dev/uinput. Existing Moonlight permissions may already cover this. "
            "Do not run the GUI as root."
        )
        dialog.setInformativeText(
            "Ask your system administrator to load uinput and grant device access. "
            "The README contains an optional udev rule. Input access can read keyboard "
            "activity across the desktop. Only recorded events are saved.\n\n"
            "Native Wayland supports desktop replay. Background routing only lists "
            "X11/Xwayland windows and may be ignored by games.\n\n"
            "Use Test mode to explore without device permissions. Global F-keys require "
            "a readable keyboard; the on-screen Stop always works."
        )
        dialog.exec()

    def closeEvent(self, event):
        self.stop()
        if getattr(self, "replay", None) and not self.replay.join(2):
            self.show_error("Playback is still stopping. Wait for input cleanup before closing.")
            event.ignore()
            return
        self.update_busy(False)
        if not self.confirm_discard():
            event.ignore()
            return
        if self.monitor:
            self.monitor.stop()
        try:
            self.recovery_path.unlink(missing_ok=True)
        except OSError:
            pass
        event.accept()
