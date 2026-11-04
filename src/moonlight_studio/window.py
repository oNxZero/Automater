import time
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QUndoStack
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import __version__, storage, x11
from .editor import StepDelegate, StepModel
from .engine import DryRun, PlaybackOptions, Replay
from .linux_input import DeviceMonitor, Recorder, UInputBackend, devices, diagnostics
from .models import Script, Step

STYLE = """
QWidget { background: #1e2030; color: #cad3f5; font-family: 'Inter', 'Segoe UI', sans-serif;
          font-size: 13px; }
QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget { background: #181926; }
QLabel#brand { color: #b7c5ff; font-size: 24px; font-weight: 800; }
QLabel#heading { font-size: 21px; font-weight: 700; }
QLabel#muted { color: #a5adcb; background: transparent; }
QLabel#status { color: #a6e3a1; background: #24273a; padding: 12px; border-radius: 8px; }
QLabel#notice { background: #2c3047; color: #c8d2f9; padding: 12px; border-radius: 8px; }
QFrame#card { background: #24273a; border-radius: 10px; }
QPushButton { background: #363a4f; border: 1px solid #494d64; border-radius: 7px;
              padding: 8px 13px; font-weight: 600; }
QPushButton:hover { background: #494d64; border-color: #8caaee; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus { border: 1px solid #8caaee; }
QPushButton:disabled { color: #6e738d; background: #25283a; border-color: #363a4f; }
QPushButton#primary { background: #8caaee; color: #181926; border-color: #8caaee; }
QPushButton#record { background: #f38ba8; color: #181926; border-color: #f38ba8; }
QPushButton#stop { color: #f38ba8; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit { background: #181926;
    border: 1px solid #494d64; border-radius: 6px; padding: 6px; selection-background-color: #506291; }
QComboBox QAbstractItemView { background: #24273a; selection-background-color: #494d64; }
QTableView { background: #1e2030; alternate-background-color: #24273a;
    border: 1px solid #363a4f; border-radius: 8px; gridline-color: #363a4f;
    selection-background-color: #40537d; }
QHeaderView::section { background: #292d43; color: #a5adcb; padding: 9px;
                      border: none; border-bottom: 1px solid #494d64; }
QListWidget { border: none; background: #1e2030; outline: none; }
QListWidget::item { padding: 9px 6px; border-radius: 5px; }
QListWidget::item:selected { background: #364463; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: #24273a; padding: 10px 16px; color: #a5adcb; }
QTabBar::tab:selected { color: #b7c5ff; border-bottom: 2px solid #8caaee; }
QSplitter::handle { background: #181926; width: 8px; }
QCheckBox { spacing: 8px; padding: 3px; }
QToolTip { background: #363a4f; color: #cad3f5; border: 1px solid #8caaee; }
"""


class Bridge(QObject):
    replay = Signal(str, object)
    hotkey = Signal(str)
    monitor_error = Signal(str)


def button(text, callback, name="", tip=""):
    widget = QPushButton(text)
    widget.setObjectName(name)
    widget.setToolTip(tip)
    widget.clicked.connect(callback)
    return widget


def label(text, name="muted"):
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.PlainText)
    return widget


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
        self.setWindowTitle("Moonlight Studio")
        self.resize(1380, 860)
        self.setMinimumSize(1000, 680)
        self.setStyleSheet(STYLE)
        self.build_ui()
        self.model.changed.connect(self.edited)
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
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(22, 18, 22, 14)
        root.setSpacing(14)
        top = QHBoxLayout()
        top.addWidget(label("☾  Moonlight Studio", "brand"))
        top.addStretch()
        self.new_btn = button("New", self.new_script, tip="Ctrl+N")
        self.open_btn = button("Open…", self.open_script, tip="Ctrl+O · Import a JSON script")
        self.save_btn = button("Save", self.save_script, tip="Ctrl+S")
        self.save_as_btn = button("Save as…", self.save_as)
        for widget in (self.new_btn, self.open_btn, self.save_btn, self.save_as_btn):
            top.addWidget(widget)
        root.addLayout(top)
        self.notice = label("Record a routine. Make it yours. Replay with control.", "notice")
        root.addWidget(self.notice)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)
        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(220)
        self.tabs.setMaximumWidth(330)
        library = QWidget()
        layout = QVBoxLayout(library)
        layout.addWidget(label("YOUR SCRIPTS"))
        self.library = QListWidget()
        self.library.setAccessibleName("Saved scripts")
        self.library.itemDoubleClicked.connect(self.open_library)
        layout.addWidget(self.library, 1)
        layout.addWidget(
            label("Double-click a script to open it.\nUse Save as to add one to your library.")
        )
        layout.addWidget(button("Load example", self.load_example))
        layout.addWidget(button("Refresh library", self.refresh_library))
        self.tabs.addTab(library, "Library")
        setup = QWidget()
        setup_layout = QVBoxLayout(setup)
        self.health = label("")
        setup_layout.addWidget(self.health)
        setup_layout.addWidget(label("INPUT DEVICES"))
        self.device_list = QListWidget()
        self.device_list.setAccessibleName("Physical input devices to monitor")
        setup_layout.addWidget(self.device_list, 1)
        setup_layout.addWidget(button("Apply / refresh devices", self.refresh_devices))
        setup_layout.addWidget(
            label("F6  Record / finish\nF7  Play / stop\nF8  Pause / resume\nF12  Emergency stop")
        )
        setup_layout.addWidget(button("Permissions & help", self.show_help))
        self.tabs.addTab(setup, "Setup")
        split.addWidget(self.tabs)

        workspace = QWidget()
        work = QVBoxLayout(workspace)
        work.setContentsMargins(10, 0, 10, 0)
        self.name = QLineEdit()
        self.name.setMaxLength(120)
        self.name.setPlaceholderText("Name your script")
        self.name.setAccessibleName("Script name")
        self.name.setStyleSheet("font-size: 21px; font-weight: 700; padding: 10px;")
        work.addWidget(self.name)
        self.stats = label("")
        work.addWidget(self.stats)
        self.table = QTableView()
        self.table.setAccessibleName("Script event editor")
        self.table.setModel(self.model)
        self.table.setItemDelegate(StepDelegate(self.table))
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for column, width in enumerate((42, 110, 115, 160, 105, 105)):
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setStretchLastSection(True)
        work.addWidget(self.table, 1)
        tools = QHBoxLayout()
        self.add_kind = QComboBox()
        self.add_kind.addItems(["Key tap", "Mouse click", "Wait", "Move", "Scroll"])
        self.add_kind.setAccessibleName("New step type")
        tools.addWidget(self.add_kind)
        tools.addWidget(button("+ Add", self.add_step))
        tools.addWidget(button("Duplicate", self.duplicate))
        tools.addWidget(button("Delete", self.delete))
        tools.addWidget(button("↑", lambda: self.move(-1), tip="Move selection up"))
        tools.addWidget(button("↓", lambda: self.move(1), tip="Move selection down"))
        work.addLayout(tools)
        undo_row = QHBoxLayout()
        self.undo_btn = button("Undo", self.undo.undo, tip="Ctrl+Z")
        self.redo_btn = button("Redo", self.undo.redo, tip="Ctrl+Shift+Z")
        undo_row.addWidget(self.undo_btn)
        undo_row.addWidget(self.redo_btn)
        undo_row.addStretch()
        undo_row.addWidget(label("Double-click a cell to edit • uncheck to skip"))
        work.addLayout(undo_row)
        self.notes = QTextEdit()
        self.notes.setPlaceholderText("Notes, game bindings, starting position…")
        self.notes.setAccessibleName("Script notes")
        self.notes.setMaximumHeight(80)
        work.addWidget(self.notes)
        self.edit_workspace = workspace
        split.addWidget(workspace)

        settings = QWidget()
        settings.setMinimumWidth(265)
        settings.setMaximumWidth(340)
        panel = QVBoxLayout(settings)
        panel.setContentsMargins(8, 0, 0, 0)
        panel.addWidget(label("Playback", "heading"))
        self.mode = QComboBox()
        self.mode.addItems(["Desktop · uinput", "Background · X11 (experimental)"])
        self.mode.currentIndexChanged.connect(self.routing_changed)
        panel.addWidget(self.mode)
        self.target = QComboBox()
        self.target.setAccessibleName("Target program window")
        self.target.setMinimumContentsLength(15)
        self.target.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        panel.addWidget(self.target)
        self.refresh_target_btn = button("Refresh windows", self.refresh_windows)
        panel.addWidget(self.refresh_target_btn)
        self.routing_hint = label("")
        panel.addWidget(self.routing_hint)
        form = QFormLayout()
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.1, 10)
        self.speed.setSingleStep(0.1)
        self.speed.setValue(1)
        self.speed.setSuffix(" ×")
        self.repeats = QSpinBox()
        self.repeats.setRange(0, 100_000)
        self.repeats.setValue(1)
        self.repeats.setSpecialValueText("Until stopped")
        self.countdown = QSpinBox()
        self.countdown.setRange(0, 30)
        self.countdown.setValue(3)
        self.countdown.setSuffix(" s")
        self.gap = QDoubleSpinBox()
        self.gap.setRange(0, 3600)
        self.gap.setValue(0.25)
        self.gap.setSuffix(" s")
        form.addRow("Speed", self.speed)
        form.addRow("Repeat", self.repeats)
        form.addRow("Start delay", self.countdown)
        form.addRow("Loop gap", self.gap)
        panel.addLayout(form)
        self.test_mode = QCheckBox("Test mode · no input sent")
        self.test_mode.setToolTip(
            "Runs the real scheduler and highlights events without emitting input"
        )
        panel.addWidget(self.test_mode)
        self.play_btn = button("▶  Play  ·  F7", self.toggle_play, "primary")
        self.pause_btn = button("Pause / resume  ·  F8", self.pause)
        self.stop_btn = button("■  Stop  ·  F12", self.stop, "stop")
        panel.addSpacing(18)
        panel.addWidget(label("Record", "heading"))
        self.capture_keys = QCheckBox("Keyboard")
        self.capture_buttons = QCheckBox("Mouse buttons & wheel")
        self.capture_motion = QCheckBox("Mouse movement")
        for widget in (self.capture_keys, self.capture_buttons, self.capture_motion):
            widget.setChecked(True)
            panel.addWidget(widget)
        self.record_btn = button("●  Record  ·  F6", self.toggle_record, "record")
        panel.addWidget(
            label("A new recording replaces the event list. Undo restores the previous steps.")
        )
        panel.addStretch()
        panel.addWidget(label(f"Moonlight Studio {__version__}  ·  Linux"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(settings)
        split.addWidget(scroll)
        split.setSizes([245, 800, 290])
        transport = QHBoxLayout()
        transport.addWidget(self.record_btn)
        transport.addWidget(self.play_btn)
        transport.addWidget(self.pause_btn)
        transport.addStretch()
        transport.addWidget(self.stop_btn)
        root.addLayout(transport)
        self.status = label("Ready", "status")
        root.addWidget(self.status)
        self.update_busy(False)
        self.routing_changed()

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
        enabled = sum(s.enabled for s in self.model.steps)
        duration = sum(s.delay_ms for s in self.model.steps if s.enabled) / 1000
        self.stats.setText(
            f"{len(self.model.steps):,} steps   ·   {enabled:,} enabled   ·   {duration:.2f}s at 1×"
        )
        title = self.name.text().strip() or "Untitled script"
        self.setWindowTitle(f"{'● ' if self.dirty() else ''}{title} — Moonlight Studio")

    def load_script(self, script, path=None):
        self.loading = True
        self.path = Path(path) if path else None
        self.name.setText(script.name)
        self.notes.setPlainText(script.notes)
        self.model.replace(script.steps)
        self.undo.clear()
        self.saved_snapshot = script.to_dict()
        self.loading = False
        self.edited()

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
            item.setData(Qt.UserRole, str(path))
            item.setToolTip(str(path))
            self.library.addItem(item)

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

    def add_step(self):
        kind = self.add_kind.currentIndex()
        choices = [
            [Step(100, "key_down", "KEY_SPACE"), Step(60, "key_up", "KEY_SPACE")],
            [Step(100, "key_down", "BTN_LEFT"), Step(60, "key_up", "BTN_LEFT")],
            [Step(250, "wait")],
            [Step(16, "move", x=10)],
            [Step(100, "scroll", y=1)],
        ]
        rows = self.selected_rows()
        at = rows[-1] + 1 if rows else len(self.model.steps)
        self.model.commit(
            self.model.steps[:at] + choices[kind] + self.model.steps[at:], "Add steps"
        )
        self.table.selectRow(at)

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
            self.new_btn,
            self.open_btn,
            self.save_btn,
            self.save_as_btn,
            self.tabs,
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
        self.record_btn.setEnabled(not getattr(self, "replay", None) or not self.replay.running)
        self.pause_btn.setEnabled(bool(getattr(self, "replay", None) and self.replay.running))
        self.stop_btn.setEnabled(busy)
        if not busy:
            self.routing_changed()

    def routing_changed(self):
        background = self.mode.currentIndex() == 1
        self.target.setEnabled(background and not self.busy)
        self.refresh_target_btn.setEnabled(background and not self.busy)
        self.routing_hint.setText(
            "Sends to one X11/Xwayland window without taking focus. Games may ignore it. "
            "Mouse movement is a virtual cursor starting at the window center."
            if background
            else "Sends to the active desktop. Focus the game during the countdown. "
            "Works on Wayland and X11 with uinput access."
        )

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
                    "Global controls ready • F6 record · F7 play · F8 pause · F12 stop"
                )
            else:
                self.notice.setText(
                    "Input access needs setup. You can edit scripts and use Test mode now. "
                    "Open Setup → Permissions & help."
                )
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
            self.tabs.setCurrentIndex(1)
            self.show_error("No selected readable input devices. Open Permissions & help in Setup.")
            return
        self.record_pending = True
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
            self.play_btn.setText("■  Stop playback  ·  F7")
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
            self.model.commit(steps, "Replace with recording")
            self.status.setText(
                f"Recording finished • {len(steps):,} steps • Undo restores previous steps"
            )
        self.record_btn.setText("●  Record  ·  F6")
        if getattr(self, "replay", None) and self.replay.running:
            self.replay.stop()
            self.status.setText("Stopping • releasing held inputs…")
        else:
            self.update_busy(False)
            self.autosave()

    def on_replay(self, event, value):
        if event == "state":
            prefix = "Test mode · " if self.test_mode.isChecked() else ""
            self.status.setText(prefix + value)
        elif event == "progress":
            row, loop = value
            self.model.highlight(row)
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
            self.play_btn.setText("▶  Play  ·  F7")
            self.update_busy(False)
            if not self.playback_error:
                self.status.setText("Playback finished • held inputs released")

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
