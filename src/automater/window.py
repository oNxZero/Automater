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
from .annotations import AnnotationsMixin
from .appearance import AppearanceMixin
from .compatibility import kde_desktop, session_type
from .compatibility_ui import CompatibilityMixin
from .designer import build_ui
from .dialogs import SaveChangesDialog
from .documents import DocumentsMixin
from .editing import EditingMixin
from .editor import StepModel, editing_command
from .engine import DryRun, PlaybackOptions, Replay
from .help_ui import getting_started
from .isolated import GameSession, IsolatedBackend
from .library import LibraryMixin
from .linux_input import DeviceMonitor, Recorder, UInputBackend, devices, diagnostics
from .models import KEY_CODES, MAX_STEPS, Script, Step
from .open_windows import WindowObserver, discover_windows, guarded_desktop, matching_x11
from .preferences import Preferences
from .run_feedback import RunFeedbackMixin
from .session_ui import SessionMixin
from .theme import icon
from .visuals import VisualsMixin
from .window_picker import WindowPicker


class Bridge(QObject):
    replay = Signal(str, object)
    hotkey = Signal(int, str)
    monitor_error = Signal(int, str)
    position_picked = Signal(int, object, str)
    session_ready = Signal(int, str)
    session_windows = Signal(int, object, str)
    library_ready = Signal(int, object)
    compatibility_ready = Signal(int, object)


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
    CompatibilityMixin,
    AppearanceMixin,
    DocumentsMixin,
    AnnotationsMixin,
    LibraryMixin,
    RunFeedbackMixin,
    SessionMixin,
    VisualsMixin,
    EditingMixin,
    QMainWindow,
):
    def __init__(self, config_dir=None, demo=False):
        super().__init__()
        self.config_dir = Path(config_dir) if config_dir else storage.prepare_data_dir()
        self.library_dir = self.config_dir / "scripts"
        self.demo = demo
        self.library_entries = {}
        self.library_generation = 0
        self.library_scan_pending = False
        self.library_scan_requested = False
        self.library_shutdown = False
        self.library_stop = threading.Event()
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
        self.record_started = time.monotonic()
        self.preview_updated_at = 0
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
        self.x11_targets = []
        self.window_picker = None
        self.window_observer = WindowObserver(self)
        self.window_observer.changed.connect(self.desktop_windows_changed)
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
        self.bridge.library_ready.connect(self.library_scanned)
        self.bridge.session_ready.connect(self.session_started)
        self.bridge.session_windows.connect(self.session_windows_ready)
        self.undo = QUndoGroup(self)
        initial_stack = QUndoStack(self)
        initial_stack.setUndoLimit(50)
        self.undo.addStack(initial_stack)
        self.undo.setActiveStack(initial_stack)
        self.model = StepModel(initial_stack)
        self.model.invalid.connect(self.show_error)
        self.model.invalid.connect(lambda _message: setattr(self, "pending_rows", None))
        self.pending_rows = None
        self.script_version = 1
        self.selection_anchor = -1
        self.active_block = None
        self._sync_selection = False
        self.blocks = []
        self.setWindowIcon(icon("automation", "#b5a4fa"))
        self.setWindowTitle("Automater")
        self.resize(1240, 800)
        self.setMinimumSize(1000, 680)
        self.appearance_dialog = None
        self.compatibility_dialog = None
        self.apply_appearance(self.preferences.theme, self.preferences.theme_colors, persist=False)
        self.build_ui()
        self.restore_preferences()
        self.apply_appearance(self.preferences.theme, self.preferences.theme_colors, persist=False)
        self.model.change_guard = self.group_inspector.flush
        self.model.changed.connect(self.edited)
        self.model.changed.connect(self.refresh_workflow)
        self.model.inputChanged.connect(
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
        self.record_timer.setInterval(16)
        self.record_timer.timeout.connect(self.record_tick)
        self.load_script(sample() if demo else Script())
        if demo:
            self.test_mode.setChecked(True)
        self.refresh_library()
        self.refresh_devices()
        self.refresh_windows()
        self.initializing = False
        if not demo and QApplication.platformName() != "offscreen" and kde_desktop():
            self.window_observer.start()
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
            (self.activate_target, prefs.activate_target),
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
        prefs.activate_target = self.activate_target.isChecked()
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
            ("Ctrl+Shift+N", self.edit_selection_notes),
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
            ("Ctrl+,", self.show_appearance),
            ("Ctrl+Z", self.undo_focused_edit),
            ("Ctrl+Shift+Z", lambda: self.undo_focused_edit(redo=True)),
        ):
            action = QAction(self)
            action.setShortcut(QKeySequence(key))
            action.triggered.connect(
                lambda checked=False, cb=callback: cb() if not self.busy else None
            )
            self.addAction(action)
        # Global F-key controls come only from evdev. Qt bindings would double-fire.

    def script(self):
        if not self.group_inspector.flush():
            raise ValueError("Group notes need a name and at most 20,000 characters")
        script = Script(
            self.name.text().strip() or "Untitled script",
            self.notes.toPlainText(),
            list(self.model.steps),
            self.script_version,
            groups={key: dict(value) for key, value in self.model.groups.items()},
        )
        if self.start_enabled.isChecked():
            script.start = {
                "x": self.start_x.value(),
                "y": self.start_y.value(),
                "settle_ms": self.start_settle.value(),
                "space": "window" if self.mode.currentIndex() else "desktop",
            }
        return script.validate()

    def undo_focused_edit(self, redo=False):
        if self.busy:
            return
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit)):
            getattr(focus, "redo" if redo else "undo")()
        elif not self.busy and self.group_inspector.flush():
            getattr(self.undo, "redo" if redo else "undo")()

    def show_getting_started(self):
        dialog = getting_started(self)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.show()

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
        is_dirty = self.dirty()
        self.setWindowTitle(f"{'● ' if is_dirty else ''}{title} — Automater")
        self.saved_badge.setText("Unsaved changes")
        self.saved_badge.setVisible(is_dirty)
        self.update_document_title(is_dirty)
        self.update_run_summary()

    def update_stats(self):
        duration = sum(s.delay_ms for s in self.model.steps if s.runnable) / 1000
        maximum = sum(s.maximum_ms for s in self.model.steps if s.runnable) / 1000
        notes = sum(block.kind == "note" for block in self.blocks)
        pieces = [f"{len(self.blocks) - notes:,} actions"]
        if notes:
            pieces.append(f"{notes} note{'s' if notes != 1 else ''}")
        if self.model.groups:
            pieces.append(f"{len(self.model.groups)} groups")
        pieces.append(f"{duration:.2f}" + (f"–{maximum:.2f} s" if maximum != duration else " s"))
        self.stats.setText(" · ".join(pieces) if self.model.steps else "")

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
        if not self.mode.currentIndex() and target is not None:
            summary = "Desktop: " + target.title
        if hasattr(self, "refresh_target_btn"):
            title = target.title if target is not None else "Choose open window…"
            self.refresh_target_btn.set_caption(title)
            self.refresh_target_btn.setToolTip(title)
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

        background = self.mode.currentIndex() != 0
        available, description = capability()
        portal_ready = bool(self.portal_connection and self.portal_connection.active)
        if portal_ready:
            description = (
                "Wayland pointer control connected. Coordinates use the approved monitors."
            )
        elif not available and session_type() == "wayland":
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
        self.portal_connect_btn.setVisible(
            session_type() == "wayland" and not available and not background
        )
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
            self.workflow.canvas.render_canvas()
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
        self.model.replace(script.steps, script.groups)
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
        result = SaveChangesDialog.ask(
            self, self.path.stem if self.path else self.name.text(), self.path, len(self.blocks)
        )
        if result == "save":
            return self.save_script()
        if result == "discard":
            self.clear_recovery()
            return True
        return False

    def clear_recovery(self):
        try:
            self.recovery_path.unlink(missing_ok=True)
        except OSError as exc:
            self.show_error(f"Could not clear recovery file: {exc}")

    def new_script(self):
        names = {doc.script.name for doc in self.documents.values()}
        names.add(self.name.text().strip())
        name, number = "Untitled workflow", 2
        while name in names:
            name = f"Untitled workflow {number}"
            number += 1
        return self.load_script(Script(name))

    def load_example(self):
        if not self.load_script(sample()):
            return
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
        opened = self.load_script(
            Script(
                "Input controls",
                "Press E, wait, release E, hold W, click and move. Test mode sends no input.",
                steps,
            )
        )
        if not opened:
            return
        self.test_mode.setChecked(True)
        self.status.setText("Input controls example · Test mode is on · F1 shows shortcuts")

    def open_script(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open script", str(self.script_dialog_directory()), "Scripts (*.json)"
        )
        if path:
            self.open_path(path)

    def open_path(self, path):
        try:
            path = Path(path).expanduser().resolve()
            script = storage.load(path)
            if not self.load_script(script, path):
                return False
            self.remember_script_directory(path.parent)
            self.remember_workflow(path, script)
            self.refresh_library()
            self.status.setText(f"Opened {Path(path).name}")
            return True
        except (ValueError, OSError) as exc:
            self.show_error(str(exc))
            return False

    def script_dialog_directory(self):
        candidates = [
            self.path.parent if self.path is not None else None,
            Path(self.preferences.script_directory) if self.preferences.script_directory else None,
        ]
        for directory in candidates:
            if directory is not None and directory.is_dir():
                return directory.resolve()
        try:
            self.library_dir.mkdir(parents=True, exist_ok=True)
            return self.library_dir.resolve()
        except OSError as exc:
            self.show_error(f"Could not create the workflow folder: {exc}")
            return self.config_dir.resolve() if self.config_dir.is_dir() else Path.home()

    def remember_script_directory(self, directory):
        self.preferences.script_directory = str(Path(directory).resolve())
        self.save_preferences()

    def save_script(self):
        if self.busy:
            return False
        if self.path is None:
            return self.save_as()
        try:
            self.path = self.path.expanduser().resolve()
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
            self.remember_script_directory(self.path.parent)
            self.saved_snapshot = script.to_dict()
            self.remember_workflow(self.path, script)
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
        filename = (
            self.path.name
            if self.path is not None
            else (default.strip() or "Untitled script") + ".json"
        )
        directory = self.script_dialog_directory()
        dialog = QFileDialog(self, "Save script", str(directory), "Scripts (*.json)")
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        dialog.setDefaultSuffix("json")
        dialog.setDirectory(str(directory))
        dialog.selectFile(filename)
        if dialog.exec() != QDialog.Accepted:
            return False
        old = self.path
        chosen = Path(dialog.selectedFiles()[0]).expanduser()
        self.path = (
            chosen if chosen.is_absolute() else Path(dialog.directory().absolutePath()) / chosen
        ).resolve()
        if self.save_script():
            return True
        self.path = old
        return False

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
        if getattr(self, "appearance_dialog", None):
            self.appearance_dialog.setEnabled(not busy)
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
            self.activate_target,
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
        self.target.setEnabled(not self.busy)
        self.refresh_target_btn.setEnabled(not self.busy)
        self.target.setVisible(False)
        self.refresh_target_btn.setVisible(True)
        self.session_controls.setVisible(self.mode.currentIndex() == 2)
        self.activate_target.setVisible(self.mode.currentIndex() == 0)
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
            else "Desktop playback uses your normal pointer. The selected window must stay focused; switching away stops the workflow."
        )
        self.update_run_summary()

    def refresh_windows(self):
        if (
            not self.demo
            and QApplication.platformName() != "offscreen"
            and kde_desktop()
            and not self.window_observer.snapshot()[2]
        ):
            self.window_observer.start()
        if self.mode.currentIndex() == 2:
            self.populate_targets(self.session_targets)
            self.session_tick()
            return
        error = ""
        try:
            self.x11_targets = x11.windows()
        except Exception as exc:
            self.x11_targets = []
            error = f"X11 windows unavailable: {exc}"
        self.target.setToolTip(error)
        self.desktop_windows_changed()

    def desktop_windows_changed(self):
        if self.busy or self.mode.currentIndex() == 2:
            return
        windows = discover_windows(self.x11_targets, self.window_observer)
        if self.mode.currentIndex() == 1:
            windows = [matching_x11(window, self.x11_targets) or window for window in windows]
        self.populate_targets(windows)
        if self.window_picker is not None:
            _, _, available, error = self.window_observer.snapshot()
            message = "" if available else error or self.target.toolTip()
            self.window_picker.set_windows(windows, message if not windows else "")

    def choose_open_window(self):
        if self.busy:
            return
        self.refresh_windows()
        picker = WindowPicker(self, self.refresh_windows)
        self.window_picker = picker
        picker.set_windows(self.available_targets)
        try:
            if picker.exec() != QDialog.Accepted:
                return
            chosen = picker.choice
            if chosen is not None and self.mode.currentIndex() == 1:
                background = matching_x11(chosen, self.x11_targets)
                if background is None:
                    self.mode.setCurrentIndex(0)
                else:
                    chosen = background
                    # Store the unambiguous X11 identity for the background backend.
                    if self.target_index(chosen) < 0:
                        self.target.addItem(chosen.title, chosen)
            self.target.setCurrentIndex(max(0, self.target_index(chosen)))
            self.update_run_summary()
        finally:
            self.window_picker = None
            picker.deleteLater()

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
        if any(self.model.steps[row].action == "note" for row in rows):
            self.show_error("Notes are visual only. Select input actions to re-record.")
            return
        if rows != list(range(rows[0], rows[-1] + 1)):
            self.show_error("Re-record one action or adjacent actions together")
            return
        self.begin_recording(rows)

    def begin_recording(self, replace_rows=None):
        if not self.group_inspector.flush():
            self.show_error("Finish the current group name/notes before recording")
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
        groups = (
            {self.model.steps[row].group_id for row in replace_rows}
            if replace_rows is not None
            else set()
        )
        self.record_group_id = next(iter(groups)) if len(groups) == 1 else ""
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
        # Arm now; the input thread gates events against the exact countdown deadline.
        self.recorder.start(
            self.capture_keys.isChecked(),
            self.capture_buttons.isChecked(),
            self.capture_motion.isChecked(),
            limit=MAX_STEPS - len(self.record_base),
            start_at=self.record_deadline,
        )
        self.record_started = self.record_deadline
        self.preview_updated_at = 0
        self.record_preview.set_snapshot(0, [], [], 0)
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
        self.update_busy(True)

    def capture_tick(self):
        if getattr(self, "replay", None) is not None and self.replay.running:
            self.render_playback()
        else:
            self.update_countdown()
        if self.recorder.active and not self.record_pending:
            now = time.monotonic()
            self.record_preview.show()
            if not self.model.steps:
                self.welcome_heading.setText("Recording your routine")
                self.welcome_description.setText(
                    "Your latest inputs appear above. Finish with F6 to edit the workflow."
                )
                self.welcome_example.hide()
            if now - self.preview_updated_at >= 0.1:
                self.record_preview.set_snapshot(
                    *self.recorder.preview(), now - self.record_started
                )
                self.preview_updated_at = now
            self.run_state.hide()
            self.status.setText("F6 adds this recording · Discard keeps the original workflow")

    def toggle_play(self):
        if getattr(self, "replay", None) and self.replay.running:
            self.stop()
            return
        if self.busy:
            return
        self.close_overlay()
        try:
            script = self.script()
            if (
                self.start_enabled.isChecked()
                and not self.test_mode.isChecked()
                and not self.mode.currentIndex()
            ):
                from .pointer import capability

                available, reason = capability()
                if not available and not (self.portal_connection and self.portal_connection.active):
                    self.show_inspector(2)
                    raise ValueError(
                        "Coordinate reset needs Wayland pointer permission. Click Connect Wayland pointer, or disable reset."
                        if session_type() == "wayland"
                        else reason
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
                target = matching_x11(target, self.x11_targets)
                if target is None:
                    raise ValueError(
                        "This window needs Active desktop mode. Choose it in the open-window picker."
                    )
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
                selected_window = self.target.currentData()
                if selected_window is not None:
                    factory = partial(
                        guarded_desktop,
                        factory,
                        selected_window,
                        self.window_observer,
                        self.activate_target.isChecked(),
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
            self.clear_run_feedback()
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
        self.record_preview.hide()
        self.welcome_heading.setText("Create your first workflow")
        self.welcome_description.setText("Click Record below, or Add action above.")
        self.welcome_example.show()
        cancelled_recording = self.record_pending and time.monotonic() < getattr(
            self, "record_deadline", float("inf")
        )
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
            if getattr(self, "record_group_id", ""):
                from dataclasses import replace

                steps = [replace(step, group_id=self.record_group_id) for step in steps]
            prefix = getattr(self, "record_prefix", [])
            suffix = getattr(self, "record_suffix", [])
            if discard_recording or not any(s.action != "wait" for s in steps):
                self.status.setText(
                    "Recording cancelled · existing actions kept"
                    if cancelled_recording
                    else "Recording discarded · existing actions kept"
                )
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
            "Automater needs read access to selected /dev/input/event* devices "
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
        self.library_shutdown = True
        self.library_stop.set()
        self.window_observer.close()
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
