from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
)

from .actions import KINDS, create_action
from .inspector import milliseconds
from .key_picker import KeyPicker
from .widgets import label


class ActionDialog(QDialog):
    def __init__(self, kind=0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add workflow action")
        self.setMinimumWidth(430)
        self.steps = None
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.addWidget(label("Add an action", "heading"))
        form = QFormLayout()
        form.setSpacing(12)
        self.kind = QComboBox()
        self.kind.addItems([name for name, _ in KINDS])
        self.kind.setCurrentIndex(kind)
        form.addRow("Action", self.kind)
        self.key = KeyPicker()
        self.key.set_code("BTN_LEFT" if kind == 1 else "KEY_SPACE")
        self.key_label = label("Key / button")
        form.addRow(self.key_label, self.key)
        self.delay = milliseconds()
        form.addRow("Delay before", self.delay)
        self.duration = milliseconds()
        self.duration.setValue(500 if kind == 2 else 100)
        self.duration_label = label("Hold for")
        form.addRow(self.duration_label, self.duration)
        self.x, self.y = QSpinBox(), QSpinBox()
        self.x_label, self.y_label = label("Relative X"), label("Relative Y")
        for widget in (self.x, self.y):
            widget.setRange(-32767, 32767)
        self.x.setValue(10 if kind == 3 else 0)
        self.y.setValue(1 if kind == 4 else 0)
        self.x.setAccessibleName("Horizontal movement or scroll")
        self.y.setAccessibleName("Vertical movement or scroll")
        form.addRow(self.x_label, self.x)
        form.addRow(self.y_label, self.y)
        layout.addLayout(form)
        self.random = QCheckBox("Random duration each time")
        layout.addWidget(self.random)
        self.maximum = milliseconds()
        self.maximum.setValue(600 if kind == 2 else 150)
        self.maximum.setAccessibleName("Maximum duration in milliseconds")
        self.maximum_label = label("Maximum duration")
        self.maximum_label.setVisible(False)
        self.maximum.setVisible(False)
        self.random.toggled.connect(self.maximum.setVisible)
        self.random.toggled.connect(self.maximum_label.setVisible)
        layout.addWidget(self.maximum_label)
        layout.addWidget(self.maximum)
        self.hint = label("")
        layout.addWidget(self.hint)
        self.error = label("")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Add action")
        buttons.accepted.connect(self.add)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.kind.currentIndexChanged.connect(self.update_kind)
        self.update_kind()

    def update_kind(self):
        kind = self.kind.currentIndex()
        previous = getattr(self, "previous_kind", kind)
        if kind != previous and kind in (3, 4):
            self.x.setValue(10 if kind == 3 else 0)
            self.y.setValue(1 if kind == 4 else 0)
        self.previous_kind = kind
        if kind == 1 and not str(self.key.currentData()).startswith("BTN_"):
            self.key.set_code("BTN_LEFT")
        key = kind in (0, 1, 5, 6)
        for widget in (self.key, self.key_label):
            widget.setVisible(key)
        timed = kind in (0, 1, 2)
        for widget in (self.duration, self.duration_label, self.random):
            widget.setVisible(timed)
        self.maximum.setVisible(timed and self.random.isChecked())
        self.maximum_label.setVisible(timed and self.random.isChecked())
        self.duration_label.setText("Timer duration" if kind == 2 else "Hold for")
        self.delay.setEnabled(kind != 2)
        for widget in (self.x, self.y, self.x_label, self.y_label):
            widget.setVisible(kind in (3, 4))
        self.x_label.setText("Horizontal notches" if kind == 4 else "Relative X")
        self.y_label.setText("Vertical notches" if kind == 4 else "Relative Y")
        hints = {
            0: "Presses the key, holds it for the duration, then releases it.",
            1: "Presses and releases a mouse button after the hold duration.",
            2: "Waits without sending input. For a random timer, set minimum duration and maximum below.",
            5: "Stays down until Release, the end of the loop, or Stop. Add a Timer to keep it held.",
            3: "Moves relative to the current pointer, in device counts. Positive X moves right; positive Y moves down. For an absolute starting point, use Settings → Start.",
            4: "Scroll notches: positive vertical moves up; negative moves down. Positive horizontal moves right. Background X11 supports at most 100 notches per action.",
            6: "Releases a key or button held by an earlier Press action.",
        }
        self.hint.setText(
            hints.get(kind, "You can edit movement or scrolling in the action properties.")
        )

    def add(self):
        try:
            kind = self.kind.currentIndex()
            self.steps = create_action(
                kind,
                self.key.code() if kind in (0, 1, 5, 6) else None,
                self.delay.value(),
                self.duration.value(),
                self.maximum.value() if self.random.isChecked() and kind in (0, 1, 2) else None,
            )
            if kind in (3, 4):
                self.steps = [replace(self.steps[0], x=self.x.value(), y=self.y.value())]
            self.accept()
        except ValueError as exc:
            self.error.setText(str(exc))
