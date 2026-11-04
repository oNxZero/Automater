import json
import math
import threading
import time
from bisect import bisect_right
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QKeySequence, QUndoGroup, QUndoStack
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QLineEdit,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QTextEdit,
)

from . import storage, x11
from .designer import build_ui
from .documents import DocumentsMixin
from .editing import EditingMixin
from .editor import StepModel, editing_command
from .engine import DryRun, PlaybackOptions, Replay
from .isolated import GameSession, IsolatedBackend
from .linux_input import DeviceMonitor, Recorder, UInputBackend, devices, diagnostics
from .models import KEY_CODES, MAX_STEPS, Script, Step
from .preferences import Preferences
from .run_feedback import RunFeedbackMixin
from .session_ui import SessionMixin
from .theme import STYLE, icon
from .visuals import VisualsMixin


class Bridge(QObject):
    replay = Signal(str, object)
    hotkey = Signal(int, str)
    monitor_error = Signal(int, str)
    position_picked = Signal(int, object, str)
    session_ready = Signal(int, str)
    session_windows = Signal(int, object, str)


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


class MainWindow(
    DocumentsMixin, RunFeedbackMixin, SessionMixin, VisualsMixin, EditingMixin, QMainWindow
):
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
        self.documents = {}
        self.active_document_id = None
        self.last_run = None
        self.saved_snapshot = Script().to_dict()
        self.loading = False
        self.busy = False
        self.record_pending = False
        self.record_replace_rows = None
        self.playback_deadline = None
        self.playback_started = False
        self.pick_deadline = None
        self.pick_generation = 0
        self.picking = False
        self.screen_picking = False
        self.overlay = None
        self.portal_connection = None
        self.game_session = GameSession()
        self.session_generation = 0
        self.session_launching = False
        self.session_query_pending = False
        self.session_targets = []
        self.connecting_pointer = False
        self.monitor = None
        self.monitor_generation = 0
        self.monitor_ok = False
        self.monitor_has_keyboard = False
        self.recorder = Recorder()
        self.bridge = Bridge()
        self.bridge.replay.connect(self.on_replay)
        self.bridge.hotkey.connect(self.route_hotkey)
        self.bridge.monitor_error.connect(self.route_monitor_error)
        self.bridge.position_picked.connect(self.position_picked)
        self.bridge.session_ready.connect(self.session_started)
        self.bridge.session_windows.connect(self.session_windows_ready)
        self.undo = QUndoGroup(self)
        initial_stack = QUndoStack(self)
        initial_stack.setUndoLimit(50)
        self.undo.addStack(initial_stack)
        self.undo.setActiveStack(initial_stack)
        self.model = StepModel(initial_stack)
        self.model.invalid.connect(self.show_error)
        self.pending_rows = None
        self.script_version = 1
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
        self.model.changed.connect(
            lambda: self.clear_run_feedback(force=True) if not self.loading else None
        )
        self.name.textChanged.connect(self.edited)
        self.notes.textChanged.connect(self.edited)
        self.add_shortcuts()
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(5000)
        self.autosave_timer.timeout.connect(self.autosave)
        self.autosave_timer.start()
        self.capture_timer = QTimer(self)
        self.capture_timer.setInterval(33)
        self.capture_timer.timeout.connect(self.capture_tick)
        self.capture_timer.start()
        self.session_timer = QTimer(self)
        self.session_timer.setInterval(1000)
        self.session_timer.timeout.connect(self.session_tick)
        self.session_timer.start()
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

    def keyPressEvent(self, event):
        fallback = {Qt.Key_F6: "record", Qt.Key_F7: "play", Qt.Key_F8: "pause", Qt.Key_F12: "stop"}
        if (not self.monitor_ok or not self.monitor_has_keyboard) and event.key() in fallback:
            if not event.isAutoRepeat():
                self.on_hotkey(fallback[event.key()])
            event.accept()
            return
        focus = QApplication.focusWidget()
        while focus is not None and focus is not self:
            if isinstance(
                focus, (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QAbstractSpinBox)
            ):
                super().keyPressEvent(event)
                return
            focus = focus.parentWidget()
        command = "help" if event.key() == Qt.Key_F1 else editing_command(event)
        if command and self.pages.currentIndex() == 0:
            self.workflow_command(command)
            event.accept()
        else:
            super().keyPressEvent(event)

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
            (self.start_x, prefs.start_x),
            (self.start_y, prefs.start_y),
            (self.start_settle, prefs.start_settle_ms),
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
        self.workflow.layout_choice.setCurrentIndex(
            self.workflow.layout_choice.findData(prefs.layout)
        )
        for widget in (self.start_x, self.start_y, self.start_settle):
            widget.valueChanged.connect(self.start_settings_changed)
        self.start_enabled.toggled.connect(self.start_settings_changed)
        self.mode.currentIndexChanged.connect(self.start_settings_changed)

    def save_preferences(self, *args):
        if self.initializing or self.loading:
            return
        prefs = self.preferences
        prefs.speed, prefs.repeats = self.speed.value(), self.repeats.value()
        prefs.countdown, prefs.loop_gap = self.countdown.value(), self.gap.value()
        prefs.capture_keys, prefs.capture_buttons = (
            self.capture_keys.isChecked(),
            self.capture_buttons.isChecked(),
        )
        prefs.capture_motion = self.capture_motion.isChecked()
        prefs.layout = self.workflow.layout_choice.currentData()
        prefs.start_x, prefs.start_y, prefs.start_settle_ms = (
            self.start_x.value(),
            self.start_y.value(),
            self.start_settle.value(),
        )
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
            ("Ctrl+T", self.new_script),
            ("Ctrl+W", lambda: self.close_document(self.document_tabs.currentIndex())),
            (
                "Ctrl+Tab",
                lambda: self.document_tabs.setCurrentIndex(
                    (self.document_tabs.currentIndex() + 1) % max(1, self.document_tabs.count())
                ),
            ),
            (
                "Ctrl+Shift+Tab",
                lambda: self.document_tabs.setCurrentIndex(
                    (self.document_tabs.currentIndex() - 1) % max(1, self.document_tabs.count())
                ),
            ),
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
        script = Script(
            self.name.text().strip() or "Untitled script",
            self.notes.toPlainText(),
            list(self.model.steps),
            self.script_version,
        )
        if self.start_enabled.isChecked():
            script.start = {
                "x": self.start_x.value(),
                "y": self.start_y.value(),
                "settle_ms": self.start_settle.value(),
                "space": "window" if self.mode.currentIndex() else "desktop",
            }
        return script.validate()

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
        self.update_document_title()
        self.update_run_summary()

    def update_stats(self):
        duration = sum(s.delay_ms for s in self.model.steps if s.enabled) / 1000
        maximum = sum(s.maximum_ms for s in self.model.steps if s.enabled) / 1000
        self.stats.setText(
            f"{len(self.blocks):,} actions · {duration:.2f}"
            + (f"–{maximum:.2f} s" if maximum != duration else " s")
            if self.model.steps
            else ""
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
        self.workflow.canvas.request_selection_visibility()

    def hide_inspector(self):
        self.inspector_panel.hide()

    def update_run_summary(self):
        if not hasattr(self, "transport_hint"):
            return
        target = self.target.currentData()
        summary = (
            "Preview · no input sent"
            if self.test_mode.isChecked()
            else ("Window: " + target.title if target is not None else "Choose a target window")
            if self.mode.currentIndex()
            else "Active desktop"
        )
        if self.start_enabled.isChecked():
            summary += f" · Start {self.start_x.value()}, {self.start_y.value()}"
        self.transport_hint.setMaximumWidth(240)
        self.transport_hint.setToolTip(summary)
        self.transport_hint.setText(
            self.transport_hint.fontMetrics().elidedText(summary, Qt.ElideRight, 230)
        )
        self.preview_banner.setVisible(self.test_mode.isChecked())
        self.real_inputs_btn.setEnabled(not self.busy)
        self.record_btn.setToolTip(
            "Append a recording to the current actions · F6"
            if self.append_recording.isChecked()
            else "Replace actions with a recording; Undo restores them · F6"
        )
        if not self.recorder.active and not self.record_pending:
            self.record_btn.setText(
                "Append · F6"
                if self.model.steps and self.append_recording.isChecked()
                else "Record · F6"
            )
        from .pointer import capability

        available, description = capability()
        background = self.mode.currentIndex() != 0
        portal_ready = bool(self.portal_connection and self.portal_connection.active)
        if portal_ready:
            description = (
                "Wayland pointer control connected. Coordinates use the approved monitors."
            )
        elif not available:
            description = "Wayland needs pointer permission for exact positioning. Connect below, then approve your monitors."
        if self.test_mode.isChecked():
            description = (
                "Test mode: cursor reset is simulated. Turn off Test mode for real movement. "
                + description
            )
        self.start_capability.setText(
            "Target window client coordinates; real cursor stays unchanged."
            if background
            else description
        )
        for widget in (self.start_x, self.start_y, self.start_settle):
            widget.setEnabled(not self.busy and self.start_enabled.isChecked())
        self.pick_position_btn.setEnabled(
            not self.busy and not background and available and self.start_enabled.isChecked()
        )
        self.portal_connect_btn.setVisible(not available and not background)
        self.portal_connect_btn.setText(
            "Reconnect pointer control" if portal_ready else "Connect Wayland pointer"
        )
        self.portal_connect_btn.setEnabled(not self.busy)
        self.pick_screen_btn.setEnabled(not self.busy and not background)
        self.preview_start_btn.setEnabled(not self.busy and not background)
        start_label = (
            f"{self.start_x.value()}, {self.start_y.value()}"
            if self.start_enabled.isChecked()
            else "START"
        )
        if self.workflow.canvas.start_label != start_label:
            self.workflow.canvas.start_label = start_label
            self.workflow.canvas.render_page()
        cycle = sum(s.delay_ms for s in self.model.steps if s.enabled) / self.speed.value() / 1000
        cycle_max = (
            sum(s.maximum_ms for s in self.model.steps if s.enabled) / self.speed.value() / 1000
        )
        if self.start_enabled.isChecked():
            cycle += self.start_settle.value() / 1000
            cycle_max += self.start_settle.value() / 1000
        count = self.repeats.value()
        estimate = f"{cycle:.2f}" + (
            f"–{cycle_max:.2f} s per cycle" if cycle_max != cycle else " s per cycle"
        )
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
            maximum_total = total + (cycle_max - cycle) * count
            estimate += (
                f" · {total:.2f}"
                + (f"–{maximum_total:.2f}" if maximum_total != total else "")
                + " s total"
            )
        else:
            estimate += " · repeats until stopped"
        self.run_estimate.setText(estimate)

    def start_settings_changed(self, *args):
        self.update_run_summary()
        if not self.loading and not self.initializing:
            self.edited()

    def pick_position(self):
        if self.busy or self.mode.currentIndex():
            return
        self.pick_generation += 1
        self.picking = True
        self.pick_deadline = time.monotonic() + 3
        self.countdown_total = 3
        self.update_busy(True)
        self.update_countdown()

    @Slot(int, object, str)
    def position_picked(self, generation, point, error):
        if generation != self.pick_generation or not self.picking:
            return
        self.picking = False
        self.pick_deadline = None
        self.countdown_banner.hide()
        self.update_busy(False)
        if error:
            self.show_error(error)
        else:
            self.start_x.setValue(point[0])
            self.start_y.setValue(point[1])
            self.status.setText(f"Starting point captured: {point[0]}, {point[1]}")

    def update_countdown(self):
        now = time.monotonic()
        deadline = (
            self.pick_deadline
            if self.picking
            else self.record_deadline
            if self.record_pending
            else self.playback_deadline
        )
        if deadline is None:
            self.countdown_banner.hide()
            return
        remaining = max(0, deadline - now)
        self.countdown_banner.setVisible(remaining > 0)
        if remaining > 0:
            self.countdown_number.setText(str(math.ceil(remaining)))
            self.countdown_message.setText(
                "Place your cursor at the starting point. F12 cancels."
                if self.picking
                else "Recording starts soon. Switch to your target window. F12 cancels."
                if self.record_pending
                else "Preview starts soon. No inputs will be sent. F12 cancels."
                if self.test_mode.isChecked()
                else "Playback starts in the selected window. Your desktop input stays free. F12 cancels."
                if self.mode.currentIndex() != 0
                else "Playback starts soon. Switch to your target window. F12 cancels."
            )
            self.countdown_progress.setValue(
                round((1 - remaining / max(0.001, self.countdown_total)) * 1000)
            )
        elif self.picking:
            self.pick_deadline = None
            generation = self.pick_generation

            def read_position():
                provider = None
                try:
                    from .pointer import coordinate, desktop_pointer

                    provider = desktop_pointer()
                    point = tuple(coordinate(v) for v in provider.position())
                    if generation == self.pick_generation and self.picking:
                        self.bridge.position_picked.emit(generation, point, "")
                except Exception as exc:
                    if generation == self.pick_generation and self.picking:
                        try:
                            self.bridge.position_picked.emit(generation, None, str(exc))
                        except RuntimeError:
                            pass
                finally:
                    if provider is not None:
                        provider.close()

            threading.Thread(target=read_position, daemon=True).start()
        else:
            self.playback_deadline = None

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

    def load_script_view(self, script, path=None):
        self.loading = True
        self.path = Path(path) if path else None
        self.script_version = script.version
        self.pending_rows = None
        self._event_selection_rows = []
        self.start_enabled.setChecked(False)
        if script.start is not None:
            self.mode.setCurrentIndex(1 if script.start["space"] == "window" else 0)
            self.start_x.setValue(script.start["x"])
            self.start_y.setValue(script.start["y"])
            self.start_settle.setValue(script.start["settle_ms"])
            self.start_enabled.setChecked(True)
        self.selection_anchor = 0 if script.steps else -1
        self.name.setText(script.name)
        self.notes.setPlainText(script.notes)
        self.model.replace(script.steps)
        self.saved_snapshot = script.to_dict()
        self.loading = False
        self.edited()
        self.navigate(0, 0)
        self.inspector_panel.hide()

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
        self.load_script(Script())

    def load_example(self):
        self.load_script(sample())
        self.test_mode.setChecked(True)
        self.status.setText("Example loaded • test mode is on")

    def load_controls_example(self):
        from .actions import create_action

        steps = (
            create_action(5, "KEY_E")
            + create_action(2, duration=200, maximum=400)
            + create_action(6, "KEY_E")
            + create_action(0, "KEY_W", duration=500, maximum=750)
            + create_action(1, "BTN_LEFT", duration=60)
            + create_action(3)
        )
        self.load_script(
            Script(
                "Input controls",
                "Press E, wait, release E, hold W, click and move. Test mode sends no input.",
                steps,
            )
        )
        self.test_mode.setChecked(True)
        self.status.setText("Input controls example · Test mode is on · F1 shows shortcuts")

    def open_script(self):
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
            for identifier, doc in self.documents.items():
                if (
                    identifier != self.active_document_id
                    and doc.path is not None
                    and doc.path.resolve() == self.path.resolve()
                ):
                    raise ValueError(
                        "That file is already open in another workflow tab. Use that tab or choose a different filename."
                    )
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
        self.open_path(path)

    def autosave(self):
        if self.loading or self.busy or not self.dirty():
            return
        try:
            storage.save(self.script(), self.recovery_path)
        except (OSError, ValueError) as exc:
            self.status.setText(f"Autosave unavailable: {exc}")

    def offer_recovery(self):
        self.recover_documents()

    def update_busy(self, busy):
        self.busy = busy
        self.document_tabs.setEnabled(not busy)
        self.new_tab_btn.setEnabled(not busy)
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
            self.start_enabled,
            self.start_x,
            self.start_y,
            self.start_settle,
            self.pick_position_btn,
        ):
            widget.setEnabled(not busy)
        self.play_btn.setEnabled(not self.recorder.active and not self.record_pending)
        if self.picking or self.screen_picking or self.connecting_pointer:
            self.play_btn.setEnabled(False)
        self.record_btn.setEnabled(not busy or self.recorder.active or self.record_pending)
        self.pause_btn.setEnabled(bool(getattr(self, "replay", None) and self.replay.running))
        self.stop_btn.setEnabled(busy)
        self.pause_btn.setVisible(
            busy and bool(getattr(self, "replay", None) and self.replay.running)
        )
        self.stop_btn.setVisible(busy)
        self.cancel_capture_btn.setVisible(self.recorder.active or self.record_pending)
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
        background = self.mode.currentIndex() != 0
        self.target.setEnabled(background and not self.busy)
        self.refresh_target_btn.setEnabled(background and not self.busy)
        self.target.setVisible(background)
        self.refresh_target_btn.setVisible(background)
        self.session_controls.setVisible(self.mode.currentIndex() == 2)
        changed = getattr(self, "last_routing_mode", None) != self.mode.currentIndex()
        self.last_routing_mode = self.mode.currentIndex()
        if changed:
            self.refresh_windows()
        elif self.mode.currentIndex() == 2 and not self.busy:
            self.populate_targets(self.session_targets)
        self.routing_hint.setText(
            "Sends to one X11/Xwayland window without taking focus. Games may ignore it. "
            "Mouse movement is a virtual cursor starting at the window center."
            if self.mode.currentIndex() == 1
            else "Runs in a separate Gamescope display. Your normal mouse, keyboard and other desktops stay independent. Launch the game here first; existing instances cannot be moved."
            if self.mode.currentIndex() == 2
            else "Sends to the active desktop. Focus the game during the countdown. "
            "Works on Wayland and X11 with uinput access."
        )
        self.update_run_summary()

    def refresh_windows(self):
        if self.mode.currentIndex() == 2:
            self.populate_targets(self.session_targets)
            self.session_tick()
            return
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
                self.monitor_has_keyboard = keyboard
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
        self.begin_recording()

    def rerecord_selection(self):
        if self.busy:
            return
        rows = self.selected_rows()
        if not rows:
            self.show_error("Select an action to re-record first")
            return
        if rows != list(range(rows[0], rows[-1] + 1)):
            self.show_error("Re-record one action or adjacent actions together")
            return
        self.begin_recording(rows)

    def begin_recording(self, replace_rows=None):
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
        if replace_rows is None and not self.append_recording.isChecked() and self.model.steps:
            if (
                QMessageBox.question(
                    self,
                    "Replace entire workflow?",
                    "Replace all existing actions with the next recording? Choose No to keep them.\n"
                    "To add actions, enable Append to current workflow in Devices.",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                != QMessageBox.Yes
            ):
                return
        self.record_replace_rows = list(replace_rows) if replace_rows is not None else None
        if replace_rows is not None:
            self.record_prefix = list(self.model.steps[: replace_rows[0]])
            self.record_suffix = list(self.model.steps[replace_rows[-1] + 1 :])
        else:
            self.record_prefix = list(self.model.steps) if self.append_recording.isChecked() else []
            self.record_suffix = []
        self.record_base = self.record_prefix + self.record_suffix
        if len(self.record_base) >= MAX_STEPS - len(KEY_CODES) - 1:
            self.show_error("Not enough space to append a recording. Start a new workflow.")
            return
        self.record_pending = True
        self.navigate(0, 0)
        self.record_deadline = time.monotonic() + self.countdown.value()
        self.countdown_total = self.countdown.value()
        self.record_btn.setText("Finish · F6")
        self.update_busy(True)
        self.record_timer.start()
        self.record_tick()

    def record_tick(self):
        if not self.record_pending:
            return
        remaining = self.record_deadline - time.monotonic()
        if remaining > 0:
            self.run_state.setText("●  STARTING")
            operation = (
                "Re-record selection"
                if self.record_replace_rows is not None
                else "Append recording"
                if self.record_prefix
                else "Record"
            )
            self.status.setText(f"{operation} starts in {remaining:.1f}s · F12 cancels")
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
        if getattr(self, "replay", None) is not None and self.replay.running:
            self.render_playback()
        else:
            self.update_countdown()
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
        self.close_overlay()
        self.clear_run_feedback()
        try:
            script = self.script()
            if (
                self.start_enabled.isChecked()
                and not self.test_mode.isChecked()
                and not self.mode.currentIndex()
            ):
                from .pointer import capability

                if not capability()[0] and not (
                    self.portal_connection and self.portal_connection.active
                ):
                    self.show_inspector(2)
                    raise ValueError(
                        "Coordinate reset needs Wayland pointer permission. Click Connect Wayland pointer, or disable reset."
                    )
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
            elif self.mode.currentIndex() == 2:
                target = self.target.currentData()
                if target is None or self.game_session.address is None:
                    raise ValueError("Launch a separate game session and select its window first")
                factory = partial(IsolatedBackend, self.game_session.address, target)
            else:
                factory = UInputBackend
                if self.portal_connection and self.portal_connection.active:
                    from .portal import PortalPointer

                    factory = partial(
                        UInputBackend, pointer_factory=lambda: PortalPointer(self.portal_connection)
                    )
            self.playback_error = False
            self.playback_started = False
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
                    (self.start_x.value(), self.start_y.value())
                    if self.start_enabled.isChecked()
                    else None,
                    self.start_settle.value() / 1000,
                ),
            )
            self.play_btn.setText("Stop · F7")
            self.play_btn.setIcon(icon("stop", "#211b30"))
            self.progress.setValue(0)
            self.update_busy(True)
        except (ValueError, RuntimeError) as exc:
            self.show_error(str(exc))

    def pause(self):
        if not self.playback_started:
            return
        if getattr(self, "replay", None) and self.replay.running:
            self.replay.pause()

    def stop(self, discard_recording=False):
        self.close_overlay()
        if self.connecting_pointer:
            self.connecting_pointer = False
            self.portal_connection.close()
            self.status.setText("Pointer connection cancelled")
        self.pick_generation += 1
        self.picking = False
        self.pick_deadline = self.playback_deadline = None
        self.countdown_banner.hide()
        if self.record_pending:
            self.record_pending = False
            self.record_timer.stop()
            self.status.setText("Recording cancelled")
        if self.recorder.active:
            steps = self.recorder.stop()
            prefix = getattr(self, "record_prefix", [])
            suffix = getattr(self, "record_suffix", [])
            if discard_recording or not any(s.action != "wait" for s in steps):
                self.status.setText("Recording discarded · existing actions kept")
            else:
                self.selection_anchor = len(prefix)
                self.pending_rows = list(range(len(prefix), len(prefix) + len(steps)))
                self.model.commit(
                    prefix + steps + suffix,
                    "Re-record selection"
                    if self.record_replace_rows is not None
                    else "Append recording"
                    if prefix
                    else "Record workflow",
                )
                self.status.setText(
                    f"Recorded {len(steps):,} events · Ctrl+Z restores previous actions"
                )
        self.record_replace_rows = None
        self.record_btn.setText("Record · F6")
        if getattr(self, "replay", None) and self.replay.running:
            self.playback_stopped = True
            self.replay.stop()
            self.status.setText("Stopping • releasing held inputs…")
        else:
            self.update_busy(False)
            self.autosave()

    def on_replay(self, event, value):
        if (
            event not in ("error", "finished")
            and getattr(getattr(self, "replay", None), "timeline", None) is not None
        ):
            if event in ("countdown", "state"):
                self.render_playback()
            return
        if event == "countdown":
            self.countdown_total = value["duration"] if isinstance(value, dict) else value
            self.playback_deadline = (
                value["deadline"] if isinstance(value, dict) else time.monotonic() + value
            )
            self.pause_btn.hide()
            self.update_countdown()
        elif event == "waiting":
            row, loop, duration = value
            self.workflow.canvas.highlight(row)
            self.workflow.update_footer()
            self.model.highlight(row)
            index = max(0, bisect_right(self.workflow.canvas.starts, row) - 1)
            name = self.blocks[index].title
            self.status.setText(
                f"{'Preview' if self.test_mode.isChecked() else 'Playing'} · loop {loop} · {name} · {duration * 1000:.0f} ms"
            )
        elif event == "state":
            prefix = "Test mode · " if self.test_mode.isChecked() else ""
            self.status.setText(prefix + value)
            self.run_state.setText(
                "Ⅱ  PAUSED"
                if value.startswith("Paused")
                else "●  PREVIEW"
                if self.test_mode.isChecked()
                else "●  RUNNING"
            )
            if value == "Playing" or value.startswith("Loop "):
                self.playback_started = True
                self.playback_deadline = None
                self.countdown_banner.hide()
                self.pause_btn.setVisible(True)
            self.pause_btn.setText("Resume · F8" if value.startswith("Paused") else "Pause · F8")
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
            self.playback_started = False
            self.playback_deadline = None
            self.countdown_banner.hide()
            self.model.highlight(-1)
            self.workflow.canvas.highlight(-1)
            self.render_playback()
            self.run_state.setText("●  READY")
            self.play_btn.setText("Run · F7")
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
        if not self.confirm_close_documents():
            event.ignore()
            return
        if self.portal_connection:
            self.portal_connection.close()
        if self.monitor:
            self.monitor_generation += 1
            self.monitor.stop()
        try:
            for doc in self.documents.values():
                doc.recovery.unlink(missing_ok=True)
        except OSError:
            pass
        event.accept()
