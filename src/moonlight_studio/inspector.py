from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .models import KEY_CODES
from .widgets import button, label
from .workflow import friendly_key


def milliseconds():
    spin = QDoubleSpinBox()
    spin.setDecimals(3)
    spin.setRange(0, 3_600_000)
    spin.setSuffix(" ms")
    spin.setSingleStep(10)
    spin.setMinimumWidth(90)
    return spin


class ActionInspector(QWidget):
    applied = Signal(object, dict)
    command = Signal(str)

    def __init__(self):
        super().__init__()
        self.block = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.caption = label("ACTION PROPERTIES", "eyebrow")
        self.title = label("Select an action", "heading")
        self.summary = label("Click a card in your workflow to customize what it does.")
        layout.addWidget(self.caption)
        layout.addWidget(self.title)
        layout.addWidget(self.summary)
        self.fields = QWidget()
        fields = QVBoxLayout(self.fields)
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setSpacing(12)
        self.enabled = QCheckBox("Include in playback")
        fields.addWidget(self.enabled)
        form = QFormLayout()
        form.setSpacing(12)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.key = QComboBox()
        for code in sorted(KEY_CODES, key=lambda c: (c.startswith("BTN_"), friendly_key(c))):
            self.key.addItem(friendly_key(code), code)
        self.key.setMaxVisibleItems(16)
        self.key.setMinimumContentsLength(8)
        self.key.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.key.setAccessibleName("Action key or mouse button")
        self.key.setToolTip("Choose a physical key or mouse button")
        self.key_label = label("Key / button")
        form.addRow(self.key_label, self.key)
        self.delay = milliseconds()
        self.delay.setAccessibleName("Delay before action in milliseconds")
        self.delay_label = label("Delay before")
        form.addRow(self.delay_label, self.delay)
        self.duration = milliseconds()
        self.duration.setAccessibleName("Action duration in milliseconds")
        self.duration_label = label("Hold for")
        form.addRow(self.duration_label, self.duration)
        self.x, self.y = QSpinBox(), QSpinBox()
        for axis in (self.x, self.y):
            axis.setRange(-32767, 32767)
        self.x_label, self.y_label = label("Horizontal"), label("Vertical")
        form.addRow(self.x_label, self.x)
        form.addRow(self.y_label, self.y)
        fields.addLayout(form)
        self.detail = label("")
        fields.addWidget(self.detail)
        self.apply_btn = button("Apply changes", self.apply, "primary", glyph="check")
        actions = QHBoxLayout()
        for text, command, glyph in (
            ("", "left", "left"),
            ("", "right", "right"),
            ("", "duplicate", "copy"),
            ("", "delete", "trash"),
        ):
            actions.addWidget(
                button(
                    text,
                    lambda checked=False, c=command: self.command.emit(c),
                    "ghost",
                    tip={
                        "left": "Move action left",
                        "right": "Move action right",
                        "duplicate": "Duplicate action",
                        "delete": "Delete action",
                    }[command],
                    glyph=glyph,
                )
            )
        self.fields.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.fields)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.apply_btn)
        layout.addLayout(actions)
        self.fields.hide()

    def select(self, block, steps):
        self.block = block
        self.fields.setVisible(block is not None)
        self.apply_btn.setEnabled(block is not None)
        if block is None:
            self.title.setText("Select an action")
            self.summary.setText("Click a card in your workflow to customize what it does.")
            return
        subset = steps[block.start : block.end]
        first = subset[0]
        self.caption.setText(f"ACTION {block.start + 1:02d}  /  {block.kind.upper()}")
        self.title.setText(block.title)
        self.summary.setText(f"Events {block.start + 1}–{block.end} in your script")
        self.enabled.setChecked(first.enabled)
        key_visible = block.kind in ("key", "mouse")
        pair = key_visible and len(subset) == 2
        self.key.setVisible(key_visible)
        self.key_label.setVisible(key_visible)
        self.key.setCurrentIndex(max(0, self.key.findData(first.code)))
        self.delay.setValue(first.delay_ms)
        self.delay_label.setText("Wait for" if block.kind == "wait" else "Delay before")
        self.duration_label.setText("Hold for" if pair else "Path duration")
        self.duration.setVisible(len(subset) > 1)
        self.duration_label.setVisible(len(subset) > 1)
        # Never silently clamp aggregate path durations to the per-event limit.
        self.duration.setMaximum(3_600_000 * max(1, len(subset) - 1))
        self.duration.setValue(sum(s.delay_ms for s in subset[1:]))
        for widget in (self.x, self.y, self.x_label, self.y_label):
            widget.setVisible(block.kind in ("move", "scroll") and len(subset) == 1)
        self.x.setValue(first.x)
        self.y.setValue(first.y)
        self.detail.setText(
            f"{len(subset):,} original samples are preserved. Use Events to edit individual samples."
            if block.kind in ("move", "scroll") and len(subset) > 1
            else "Timing is measured in milliseconds. 1,000 ms = 1 second."
        )

    def apply(self):
        if self.block:
            self.applied.emit(
                self.block,
                {
                    "enabled": self.enabled.isChecked(),
                    "code": self.key.currentData(),
                    "delay": self.delay.value(),
                    "duration": self.duration.value(),
                    "x": self.x.value(),
                    "y": self.y.value(),
                },
            )
