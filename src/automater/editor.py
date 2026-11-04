import html
from copy import deepcopy
from dataclasses import replace

from PySide6.QtCore import QAbstractTableModel, Qt, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
    QStyledItemDelegate,
    QTableView,
)

from .models import ACTIONS, KEY_CODES, MAX_STEPS, Script
from .theme import paint_color

FIELDS = ("enabled", "delay_ms", "action", "code", "x", "y", "delay_max_ms")
HEADERS = (
    "On",
    "Min delay · ms",
    "Action",
    "Key / button",
    "X / horizontal",
    "Y / vertical",
    "Max delay · ms",
)


class Change(QUndoCommand):
    def __init__(self, model, steps, text, groups):
        super().__init__(text)
        self.model, self.before, self.after = model, list(model.steps), list(steps)
        self.before_groups, self.after_groups = deepcopy(model.groups), deepcopy(groups)

    def redo(self):
        self.model.replace(self.after, self.after_groups)

    def undo(self):
        self.model.replace(self.before, self.before_groups)


class StepModel(QAbstractTableModel):
    changed = Signal()
    inputChanged = Signal()
    invalid = Signal(str)

    def __init__(self, undo: QUndoStack):
        super().__init__()
        self.steps = []
        self.last_runtime_changed = True
        self.resetting = False
        self.groups = {}
        self.undo = undo
        self.playing_row = -1
        self.execution_trace = None
        self.change_guard = lambda: True

    def replace(self, steps, groups=None):
        self.last_runtime_changed = len(steps) != len(self.steps) or any(
            any(getattr(a, field) != getattr(b, field) for field in FIELDS)
            for a, b in zip(self.steps, steps)
        )
        self.resetting = True
        self.beginResetModel()
        self.steps = list(steps)
        source = self.groups if groups is None else groups
        used = {step.group_id for step in steps if step.group_id}
        self.groups = deepcopy({key: value for key, value in source.items() if key in used})
        self.endResetModel()
        self.resetting = False
        self.changed.emit()
        if self.last_runtime_changed:
            self.inputChanged.emit()

    def commit(self, steps, text, groups=None):
        if not self.change_guard():
            self.invalid.emit("Finish the current group name/notes before editing actions")
            return False
        if len(steps) > MAX_STEPS:
            self.invalid.emit(f"At most {MAX_STEPS:,} steps are supported")
            return False
        source = self.groups if groups is None else groups
        used = {step.group_id for step in steps if step.group_id}
        groups = {key: value for key, value in source.items() if key in used}
        try:
            Script(steps=list(steps), groups=groups).validate()
        except ValueError as exc:
            self.invalid.emit(str(exc))
            return False
        if steps != self.steps or groups != self.groups:
            self.undo.push(Change(self, steps, text, groups))
        return True

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.steps)

    def columnCount(self, parent=None):
        return len(FIELDS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return HEADERS[section] if orientation == Qt.Horizontal else section + 1

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        step = self.steps[index.row()]
        value = getattr(step, FIELDS[index.column()])
        if role == Qt.CheckStateRole and index.column() == 0:
            return Qt.Checked if value else Qt.Unchecked
        if role == Qt.ToolTipRole and step.action == "note":
            return "<qt>" + html.escape(step.text).replace("\n", "<br>") + "</qt>"
        if role in (Qt.DisplayRole, Qt.EditRole) and index.column() != 0:
            if role == Qt.DisplayRole and index.column() == 3 and step.action == "note":
                return step.title or "Note"
            if role == Qt.DisplayRole and value is None:
                return "Fixed"
            return round(value, 3) if isinstance(value, float) else value
        if role == Qt.BackgroundRole and index.row() == self.playing_row:
            return paint_color("#364463")
        if role == Qt.BackgroundRole and self.execution_trace:
            trace = self.execution_trace
            if trace["phase"] == "finished":
                if index.row() == trace["failed_row"]:
                    return paint_color("#593245")
                if index.row() == trace["last_activity_row"]:
                    return paint_color(
                        "#2b4059" if index.row() <= trace["completed_row"] else "#54452d"
                    )
            if step.runnable and index.row() <= trace["completed_row"]:
                return paint_color("#243e39")
        if role == Qt.ForegroundRole and not step.enabled:
            return paint_color("#7d859f")

    def flags(self, index):
        if not index.isValid() or not 0 <= index.row() < len(self.steps):
            return Qt.NoItemFlags
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if self.steps[index.row()].action == "note" and index.column() not in (0, 2):
            return base
        return base | (Qt.ItemIsUserCheckable if index.column() == 0 else Qt.ItemIsEditable)

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid():
            return False
        field = FIELDS[index.column()]
        if field == "enabled" and role == Qt.CheckStateRole:
            value = value == Qt.Checked.value or value == Qt.Checked
        elif role != Qt.EditRole:
            return False
        try:
            values = {field: value}
            old = self.steps[index.row()]
            if field == "action" and str(value).startswith("key_") and not old.code:
                values["code"] = "KEY_SPACE"
            step = replace(old, **values)
            steps = list(self.steps)
            steps[index.row()] = step
            return self.commit(steps, "Edit step")
        except (ValueError, TypeError) as exc:
            self.invalid.emit(str(exc))
            return False

    def highlight(self, row):
        old, self.playing_row = self.playing_row, row
        for value in (old, row):
            if 0 <= value < len(self.steps):
                self.dataChanged.emit(self.index(value, 0), self.index(value, len(FIELDS) - 1))

    def set_execution(self, trace):
        previous = self.execution_trace
        self.execution_trace = dict(trace)
        if not self.steps:
            return
        old = previous["completed_row"] if previous else -1
        new = trace["completed_row"]
        if not previous or new < old or trace["phase"] == "finished":
            first, end = 0, max(old, new, trace["last_activity_row"], trace["failed_row"])
        else:
            first, end = min(old, new), max(old, new)
        first, end = max(0, first), min(len(self.steps) - 1, end)
        if end >= first:
            self.dataChanged.emit(
                self.index(first, 0), self.index(end, len(FIELDS) - 1), [Qt.BackgroundRole]
            )

    def clear_execution(self):
        self.execution_trace = None
        if self.steps:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self.steps) - 1, len(FIELDS) - 1),
                [Qt.BackgroundRole],
            )


class StepDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        column = index.column()
        if column in (2, 3):
            widget = QComboBox(parent)
            widget.addItems(
                [action for action in ACTIONS if action != "note"]
                if column == 2
                else [""] + sorted(KEY_CODES)
            )
            widget.setEditable(column == 3)
            return widget
        if column in (1, 6):
            widget = QDoubleSpinBox(parent)
            widget.setRange(-1 if column == 6 else 0, 3_600_000)
            if column == 6:
                widget.setSpecialValueText("Fixed")
            widget.setDecimals(3)
            return widget
        widget = QSpinBox(parent)
        widget.setRange(-32767, 32767)
        return widget

    def setEditorData(self, editor, index):
        value = index.data(Qt.EditRole)
        if isinstance(editor, QComboBox):
            editor.setCurrentText(str(value))
        else:
            editor.setValue(-1 if value is None else value)

    def setModelData(self, editor, model, index):
        value = editor.currentText() if isinstance(editor, QComboBox) else editor.value()
        if index.column() == 6 and value < 0:
            value = None
        model.setData(index, value)


def editing_command(event):
    if event.modifiers() & Qt.ControlModifier:
        return {
            Qt.Key_C: "copy",
            Qt.Key_X: "cut",
            Qt.Key_V: "paste",
            Qt.Key_A: "select_all",
            Qt.Key_D: "duplicate",
            Qt.Key_G: "ungroup" if event.modifiers() & Qt.ShiftModifier else "group",
            Qt.Key_Z: "redo" if event.modifiers() & Qt.ShiftModifier else "undo",
        }.get(event.key())
    return {
        Qt.Key_Delete: "delete",
        Qt.Key_Backspace: "delete",
        Qt.Key_Escape: "clear_selection",
    }.get(event.key())


class EventTable(QTableView):
    command = Signal(str)

    def keyPressEvent(self, event):
        command = editing_command(event)
        if command and self.state() != QAbstractItemView.EditingState:
            self.command.emit(command)
        else:
            super().keyPressEvent(event)
