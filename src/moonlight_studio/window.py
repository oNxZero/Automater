import json
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
from .models import KEY_CODES, MAX_STEPS, Script, Step
from .preferences import Preferences
from .theme import STYLE, icon
from .workflow import blocks_for


class Bridge(QObject):
    replay = Signal(str, object)
    hotkey = Signal(int, str)
    monitor_error = Signal(int, str)


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
        self.preferences_path = self.config_dir / "preferences.json"
        self.initializing = True
        self.preferences_error = ""
        try:
            self.preferences = Preferences.load(self.preferences_path)
        except (OSError, ValueError) as exc:
            self.preferences = Preferences()
            self.preferences_error = str(exc)
        self.path = None
        self.saved_snapshot = Script().to_dict()
        self.loading = False
        self.busy = False
        self.record_pending = False
        self.monitor = None
        self.monitor_generation = 0
        self.monitor_ok = False
        self.recorder = Recorder()
        self.bridge = Bridge()
        self.bridge.replay.connect(self.on_replay)
        self.bridge.hotkey.connect(self.route_hotkey)
        self.bridge.monitor_error.connect(self.route_monitor_error)
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
        self.resize(1240, 800)
        self.setMinimumSize(1000, 680)
        self.setStyleSheet(STYLE)
        self.build_ui()
        self.restore_preferences()
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
        self.initializing = False
        if self.preferences_error:
            self.show_error("Settings could not be loaded; using defaults.")
            self.device_details.append(self.preferences_error)
        if not demo:
            QTimer.singleShot(0, self.offer_recovery)

    def build_ui(self):
        build_ui(self)

    @Slot(bool)
    def update_undo_actions(self, _enabled=False):
        self.undo_btn.setEnabled(not self.busy and self.undo.canUndo())
        self.redo_btn.setEnabled(not self.busy and self.undo.canRedo())

    @Slot(int, str)
    def route_hotkey(self, generation, action):
        if generation == self.monitor_generation:
            self.on_hotkey(action)

    @Slot(int, str)
    def route_monitor_error(self, generation, message):
        if generation == self.monitor_generation:
            self.on_monitor_error(message)

    def restore_preferences(self):
        prefs = self.preferences
        for widget, value in (
            (self.speed, prefs.speed),
            (self.repeats, prefs.repeats),
            (self.countdown, prefs.countdown),
            (self.gap, prefs.loop_gap),
        ):
            widget.setValue(value)
            widget.valueChanged.connect(self.save_preferences)
        for widget, value in (
            (self.capture_keys, prefs.capture_keys),
            (self.capture_buttons, prefs.capture_buttons),
            (self.capture_motion, prefs.capture_motion),
            (self.append_recording, prefs.append_recording),
            (self.test_mode, prefs.test_mode),
        ):
            widget.setChecked(value)
            widget.toggled.connect(self.save_preferences)
        self.update_run_summary()

    def save_preferences(self, *args):
        if self.initializing:
            return
        prefs = self.preferences
        prefs.speed, prefs.repeats = self.speed.value(), self.repeats.value()
        prefs.countdown, prefs.loop_gap = self.countdown.value(), self.gap.value()
        prefs.capture_keys, prefs.capture_buttons = (
            self.capture_keys.isChecked(),
            self.capture_buttons.isChecked(),
        )
        prefs.capture_motion = self.capture_motion.isChecked()
        prefs.append_recording, prefs.test_mode = (
            self.append_recording.isChecked(),
            self.test_mode.isChecked(),
        )
        self.update_run_summary()
        try:
            prefs.save(self.preferences_path)
        except (OSError, ValueError) as exc:
            self.status.setText("Could not save settings.")
            self.device_details.append(str(exc))

    def recommend_devices(self):
        self.preferences.device_ids = None
        self.device_list.clear()
        self.refresh_devices()

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
        self.saved_badge.setText("Unsaved" if self.dirty() else "")
        self.update_run_summary()

    def update_stats(self):
        duration = sum(s.delay_ms for s in self.model.steps if s.enabled) / 1000
        self.stats.setText(
            f"{len(self.blocks):,} actions · {duration:.2f} s" if self.model.steps else ""
        )

    def navigate(self, page, view=0):
        if self.busy and page != 0:
            return
        self.pages.setCurrentIndex(page)
        self.workspace_header.setVisible(page == 0)
        if page == 0:
            if not self.model.steps and view == 0:
                self.inspector_panel.hide()
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

    def hide_inspector(self):
        self.inspector_panel.hide()

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
        self.record_btn.setToolTip(
            "Append a recording to the current actions · F6"
            if self.append_recording.isChecked()
            else "Replace actions with a recording; Undo restores them · F6"
        )
        cycle = sum(s.delay_ms for s in self.model.steps if s.enabled) / self.speed.value() / 1000
        count = self.repeats.value()
        estimate = f"{cycle:.2f} s per cycle"
        if count:
            total = (
                max(
                    self.countdown.value(),
                    UInputBackend.startup_delay
                    if not self.test_mode.isChecked() and self.mode.currentIndex() == 0
                    else 0,
                )
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
            self.select_block(self.blocks[index], open_inspector=False)
        else:
            self.active_block = None
            self.action_inspector.select(None, self.model.steps)
        if self.pages.currentIndex() == 0:
            self.navigate(0, 1 if self.events_btn.isChecked() else 0)

    def select_block(self, block, open_inspector=True):
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
            if open_inspector:
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
        self.inspector_panel.hide()
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
        if self.active_block:
            self.select_block(self.active_block)

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
            self.append_recording,
            self.apply_devices_btn,
        ):
            widget.setEnabled(not busy)
        self.play_btn.setEnabled(not self.recorder.active and not self.record_pending)
        self.record_btn.setEnabled(not busy or self.recorder.active or self.record_pending)
        self.pause_btn.setEnabled(bool(getattr(self, "replay", None) and self.replay.running))
        self.stop_btn.setEnabled(busy)
        self.pause_btn.setVisible(
            busy and bool(getattr(self, "replay", None) and self.replay.running)
        )
        self.stop_btn.setVisible(busy)
        self.run_state.setVisible(busy)
        self.progress.setVisible(busy)
        for nav in self.nav_buttons[2:]:
            nav.setEnabled(not busy)
        self.undo_btn.setEnabled(not busy and self.undo.canUndo())
        self.redo_btn.setEnabled(not busy and self.undo.canRedo())
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
            self.device_list.item(i).data(Qt.UserRole + 1): self.device_list.item(i).checkState()
            for i in range(self.device_list.count())
            if self.device_list.item(i).flags() & Qt.ItemIsEnabled
        }
        self.monitor_generation += 1
        generation = self.monitor_generation
        self.monitor_ok = False
        self.device_badge.setText("Devices")
        try:
            if self.monitor and not self.monitor.stop():
                raise RuntimeError(
                    "The previous input listener is still stopping. Try refresh again."
                )
            self.monitor = None
            found = devices()
            self.device_list.clear()
            selected_ids = self.preferences.device_ids
            for device in found:
                kind = (
                    "Keyboard + mouse"
                    if device.keyboard and device.mouse
                    else "Keyboard"
                    if device.keyboard
                    else "Mouse"
                    if device.mouse
                    else "Input device"
                )
                text = (
                    f"{device.name}\n{kind}"
                    if device.readable
                    else f"{device.name}\n{device.issue or 'Permission needed'}"
                )
                if device.readable and device.issue:
                    text += " · " + device.issue
                item = QListWidgetItem(text)
                identity = device.identifier or "path:" + device.path
                item.setData(Qt.UserRole, device.path)
                item.setData(Qt.UserRole + 1, identity)
                item.setData(Qt.UserRole + 2, device.keyboard)
                item.setToolTip(device.path + (" · " + device.issue if device.issue else ""))
                item.setIcon(icon("key" if device.keyboard else "mouse"))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                checked = previous.get(
                    identity,
                    Qt.Checked
                    if selected_ids is None or identity in selected_ids
                    else Qt.Unchecked,
                )
                item.setCheckState(checked if device.readable else Qt.Unchecked)
                if not device.readable:
                    item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                self.device_list.addItem(item)
            selected = [
                self.device_list.item(i)
                for i in range(self.device_list.count())
                if self.device_list.item(i).checkState() == Qt.Checked
            ]
            paths = [item.data(Qt.UserRole) for item in selected]
            if not self.initializing and any(d.readable for d in found):
                present = {d.identifier or "path:" + d.path for d in found if d.readable}
                missing = set(self.preferences.device_ids or []) - present
                self.preferences.device_ids = sorted(
                    missing | {i.data(Qt.UserRole + 1) for i in selected}
                )
                self.save_preferences()
            info = diagnostics(found)
            self.device_details.setPlainText(json.dumps(info, indent=2))
            output = (
                "Desktop replay ready"
                if info["uinput_writable"]
                else "Desktop replay needs input access"
            )
            self.health.setText(
                f"{len(paths)} selected · {info['readable_devices']} available\n{output}"
            )
            if paths:
                self.monitor = DeviceMonitor(
                    paths,
                    self.recorder,
                    partial(self.bridge.hotkey.emit, generation),
                    partial(self.bridge.monitor_error.emit, generation),
                )
                self.monitor.start()  # Returns only after physical devices are open.
                self.monitor_ok = True
                keyboard = any(i.data(Qt.UserRole + 2) for i in selected)
                self.notice.setText(
                    "Input devices connected. Your selection is ready."
                    if keyboard
                    else "Mouse connected. Select a keyboard too if you want global shortcuts."
                )
                self.device_badge.setToolTip(self.notice.text())
            else:
                self.notice.setText(
                    "Choose a keyboard and mouse, then apply your selection."
                    if info["readable_devices"]
                    else "No readable input devices. Open Input access help below. Editing and Test mode are available."
                )
                self.device_badge.setText("Devices •")
                self.device_badge.setToolTip("Input setup needed")
        except Exception as exc:
            self.notice.setText(
                "Could not connect input devices. Refresh, or open Input access help below."
            )
            self.device_badge.setText("Devices •")
            self.device_details.append(str(exc))
            self.status.setText("Input setup needs attention. Open Devices.")

    def on_monitor_error(self, text):
        self.monitor_ok = False
        if getattr(self, "replay", None) and self.replay.running:
            self.playback_error = True
        if self.busy:
            self.stop()
        self.notice.setText(
            "An input device disconnected or stopped responding. Refresh the device list to reconnect."
        )
        self.device_badge.setText("Devices •")
        self.device_details.append(text)
        self.show_error(
            "Recording limit reached. Start a new workflow to continue."
            if text.startswith("Recording limit")
            else "Input events were dropped. Recording stopped; refresh Devices and try again."
            if "events were dropped" in text
            else "Input monitoring stopped. Open Devices and refresh to reconnect."
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
        self.record_base = list(self.model.steps) if self.append_recording.isChecked() else []
        if len(self.record_base) >= MAX_STEPS - len(KEY_CODES) - 1:
            self.show_error("Not enough space to append a recording. Start a new workflow.")
            return
        self.record_pending = True
        self.navigate(0, 0)
        self.record_deadline = time.monotonic() + self.countdown.value()
        self.record_btn.setText("Finish")
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
            limit=MAX_STEPS - len(self.record_base),
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
            self.play_btn.setText("Stop")
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
            prefix = getattr(self, "record_base", [])
            self.selection_anchor = len(prefix) if steps else -1
            self.model.commit(
                prefix + steps, "Append recording" if prefix else "Replace with recording"
            )
            self.status.setText(
                f"Recording finished • {len(steps):,} steps • Undo restores previous steps"
            )
        self.record_btn.setText("Record")
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
            self.play_btn.setText("Run")
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
            self.monitor_generation += 1
            self.monitor.stop()
        try:
            self.recovery_path.unlink(missing_ok=True)
        except OSError:
            pass
        event.accept()
