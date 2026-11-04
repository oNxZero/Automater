from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .key_picker import KeyPicker
from .widgets import button, label


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
        self.targets = []
        self.loading = False
        self.changed_fields = set()
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
        self.key = KeyPicker()
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
        self.delay_random = QCheckBox("Random delay")
        form.addRow(self.delay_random)
        self.delay_max = milliseconds()
        self.delay_max.setToolTip("Maximum delay; the delay above is the minimum")
        self.delay_max_label = label("Up to")
        form.addRow(self.delay_max_label, self.delay_max)
        self.delay_random.toggled.connect(self.delay_max.setEnabled)
        self.delay_random.checkStateChanged.connect(self.update_range_fields)
        self.duration = milliseconds()
        self.duration.setAccessibleName("Action duration in milliseconds")
        self.duration_label = label("Hold for")
        form.addRow(self.duration_label, self.duration)
        self.duration_random = QCheckBox("Random duration")
        form.addRow(self.duration_random)
        self.duration_max = milliseconds()
        self.duration_max_label = label("Up to")
        form.addRow(self.duration_max_label, self.duration_max)
        self.duration_random.toggled.connect(self.duration_max.setEnabled)
        self.duration_random.checkStateChanged.connect(self.update_range_fields)
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
        self.fields.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        for widget in (self.caption, self.title, self.summary, self.fields):
            content_layout.addWidget(widget)
        content_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.apply_btn)
        self.preview_btn = button(
            "Show pointer path", lambda: self.command.emit("preview_pointer"), "ghost", glyph="move"
        )
        layout.addWidget(self.preview_btn)
        self.rerecord_btn = button(
            "Re-record selection", lambda: self.command.emit("rerecord"), "ghost", glyph="record"
        )
        layout.addWidget(self.rerecord_btn)
        self.fields.hide()
        for widget, signal, field in (
            (self.enabled, "checkStateChanged", "enabled"),
            (self.key, "editTextChanged", "code"),
            (self.delay, "valueChanged", "delay"),
            (self.delay_random, "checkStateChanged", "delay_max"),
            (self.delay_max, "valueChanged", "delay_max"),
            (self.duration, "valueChanged", "duration"),
            (self.duration_random, "checkStateChanged", "duration_max"),
            (self.duration_max, "valueChanged", "duration_max"),
            (self.x, "valueChanged", "x"),
            (self.y, "valueChanged", "y"),
        ):
            getattr(widget, signal).connect(lambda *args, f=field: self.mark_changed(f))

    def mark_changed(self, field):
        if not self.loading:
            self.changed_fields.add(field)

    def update_range_fields(self, *args):
        if not hasattr(self, "duration_max"):
            return
        for widget in (self.delay_max, self.delay_max_label):
            widget.setVisible(self.delay_random.isChecked())
        for widget in (self.duration_max, self.duration_max_label):
            widget.setVisible(self.duration_random.isChecked() and not self.duration.isHidden())

    def select(self, block, steps):
        self.loading = True
        self.changed_fields.clear()
        self.targets = [block] if block else []
        self.block = block
        self.preview_btn.setVisible(block is not None and block.kind == "move")
        self.rerecord_btn.setVisible(block is not None)
        self.apply_btn.setText("Apply changes")
        self.enabled.setTristate(False)
        self.delay_random.setTristate(False)
        self.duration_random.setTristate(False)
        for widget in (
            self.delay,
            self.delay_max,
            self.duration,
            self.duration_max,
            self.x,
            self.y,
        ):
            widget.setMinimum(-32767 if widget in (self.x, self.y) else 0)
            widget.setSpecialValueText("")
        self.fields.setVisible(block is not None)
        self.apply_btn.setEnabled(block is not None)
        if block is None:
            self.title.setText("Select an action")
            self.summary.setText("Click a card in your workflow to customize what it does.")
            self.loading = False
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
        self.delay_random.setChecked(first.delay_max_ms is not None)
        self.delay_max.setValue(first.maximum_ms)
        self.delay_max.setEnabled(self.delay_random.isChecked())
        self.delay_label.setText("Wait for" if block.kind == "wait" else "Delay before")
        self.duration_label.setText("Hold for" if pair else "Path duration")
        self.duration.setVisible(len(subset) > 1)
        self.duration_label.setVisible(len(subset) > 1)
        # Never silently clamp aggregate path durations to the per-event limit.
        self.duration.setMaximum(3_600_000 * max(1, len(subset) - 1))
        self.duration.setValue(sum(s.delay_ms for s in subset[1:]))
        self.duration_random.setVisible(len(subset) > 1)
        self.duration_max.setVisible(len(subset) > 1)
        self.duration_max_label.setVisible(len(subset) > 1)
        self.duration_max.setMaximum(3_600_000 * max(1, len(subset) - 1))
        self.duration_max.setValue(sum(s.maximum_ms for s in subset[1:]))
        self.duration_random.setChecked(any(s.delay_max_ms is not None for s in subset[1:]))
        self.duration_max.setEnabled(self.duration_random.isChecked())
        for widget in (self.x, self.y, self.x_label, self.y_label):
            widget.setVisible(block.kind in ("move", "scroll") and len(subset) == 1)
        self.x.setValue(first.x)
        self.y.setValue(first.y)
        self.detail.setText(
            f"{len(subset):,} original samples are preserved. Use Events to edit individual samples."
            if block.kind in ("move", "scroll") and len(subset) > 1
            else "Timing is measured in milliseconds. 1,000 ms = 1 second."
        )
        self.loading = False
        self.update_range_fields()

    def apply(self):
        if self.block:
            try:
                code = (
                    self.key.code()
                    if self.block.kind in ("key", "mouse")
                    and (len(self.targets) == 1 or "code" in self.changed_fields)
                    else ""
                )
            except ValueError as exc:
                self.detail.setText(str(exc))
                return
            self.applied.emit(
                self.targets if len(self.targets) > 1 else self.block,
                {
                    "enabled": self.enabled.isChecked(),
                    "code": code,
                    "delay": self.delay.value(),
                    "duration": self.duration.value(),
                    "delay_max": self.delay_max.value() if self.delay_random.isChecked() else None,
                    "duration_max": self.duration_max.value()
                    if self.duration_random.isChecked()
                    else None,
                    "x": self.x.value(),
                    "y": self.y.value(),
                    "_changed": set(self.changed_fields) if len(self.targets) > 1 else None,
                },
            )

    def select_many(self, blocks, steps):
        def shape(block):
            first = steps[block.start]
            return (
                block.kind,
                "hold"
                if block.kind in ("key", "mouse") and block.end - block.start == 2
                else first.action,
            )

        compatible = len({shape(b) for b in blocks}) == 1
        self.select(blocks[0] if compatible else None, steps)
        self.caption.setText("SELECTION")
        self.title.setText(f"{len(blocks):,} actions selected")
        self.summary.setText(
            "Only changed settings apply to every selected action. Mixed values differ."
            if compatible
            else "Select matching action types to edit together. Copy, delete and randomize work for mixed types."
        )
        if not compatible:
            return
        self.targets = list(blocks)
        self.loading = True
        self.apply_btn.setText(f"Apply to {len(blocks)} actions")
        subsets = [steps[b.start : b.end] for b in blocks]
        if not all(len(s) > 1 for s in subsets):
            for widget in (
                self.duration,
                self.duration_label,
                self.duration_random,
                self.duration_max,
                self.duration_max_label,
            ):
                widget.hide()
        if not all(len(s) == 1 for s in subsets):
            for widget in (self.x, self.y, self.x_label, self.y_label):
                widget.hide()
        for widget, values in (
            (self.delay, [s[0].delay_ms for s in subsets]),
            (self.delay_max, [s[0].maximum_ms for s in subsets]),
            (self.duration, [sum(x.delay_ms for x in s[1:]) for s in subsets]),
            (self.duration_max, [sum(x.maximum_ms for x in s[1:]) for s in subsets]),
            (self.x, [s[0].x for s in subsets]),
            (self.y, [s[0].y for s in subsets]),
        ):
            if len(set(values)) > 1:
                if widget not in (self.x, self.y):
                    widget.setMinimum(-1)
                    widget.setSpecialValueText("Mixed")
                    widget.setValue(-1)
                else:
                    widget.setMinimum(-32768)
                    widget.setSpecialValueText("Mixed")
                    widget.setValue(-32768)
        codes = {s[0].code for s in subsets}
        if len(codes) > 1:
            self.key.setCurrentIndex(-1)
            self.key.lineEdit().setPlaceholderText("Multiple keys — choose to change all")
        if len({s[0].enabled for s in subsets}) > 1:
            self.enabled.setTristate(True)
            self.enabled.setCheckState(Qt.PartiallyChecked)
        for widget, values in (
            (self.delay_random, [s[0].delay_max_ms is not None for s in subsets]),
            (
                self.duration_random,
                [any(x.delay_max_ms is not None for x in s[1:]) for s in subsets],
            ),
        ):
            if len(set(values)) > 1:
                widget.setTristate(True)
                widget.setCheckState(Qt.PartiallyChecked)
        self.detail.setText(
            "Apply is one undoable change. Untouched keys, coordinates and timings stay as they are."
        )
        self.changed_fields.clear()
        self.loading = False
        self.update_range_fields()
