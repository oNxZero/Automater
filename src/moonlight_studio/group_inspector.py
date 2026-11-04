"""Editable notes belong to a colored group, never to a playback action."""

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QComboBox, QLineEdit, QTextEdit, QVBoxLayout, QWidget

from .widgets import button, label

PALETTE = (
    ("Lavender", "#b5a4fa"),
    ("Blue", "#83b8f2"),
    ("Mint", "#75d6c0"),
    ("Amber", "#e8c58a"),
    ("Rose", "#f2a3bc"),
)


class GroupNotesInspector(QWidget):
    applied = Signal(str, str, str, str)
    command = Signal(str, str)
    draftChanged = Signal()

    def __init__(self):
        super().__init__()
        self.identity = None
        self.loading = False
        self.pending = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.flush)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(label("GROUP NOTES", "eyebrow"))
        self.hint = label(
            "Select actions, press Ctrl+G, then click the colored rectangle to explain that section."
        )
        layout.addWidget(self.hint)
        self.fields = QWidget()
        fields = QVBoxLayout(self.fields)
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setSpacing(12)
        self.name = QLineEdit()
        self.name.setMaxLength(120)
        self.name.setAccessibleName("Group name")
        self.color = QComboBox()
        self.color.setAccessibleName("Group color")
        for text, value in PALETTE:
            self.color.addItem(text, value)
        self.text = QTextEdit()
        self.text.setMinimumHeight(160)
        self.text.setAcceptRichText(False)
        self.text.setAccessibleName("Notes for selected group")
        self.text.setPlaceholderText(
            "Explain this section, add instructions, or describe what to check…"
        )
        fields.addWidget(label("Name"))
        fields.addWidget(self.name)
        fields.addWidget(self.color)
        fields.addWidget(self.text, 1)
        self.status = label("Changes save automatically · Ctrl+Z to undo")
        # Keep two lines available for status text so switching between the
        # initial hint, Saving and Saved cannot resize the editor while typing.
        self.status.setMinimumHeight(36)
        fields.addWidget(self.status)
        self.save = button("Save group notes", self.flush, "primary", glyph="check")
        fields.addWidget(self.save)
        fields.addWidget(
            button(
                "Select group actions", lambda: self.command.emit(self.identity, "select"), "ghost"
            )
        )
        fields.addWidget(
            button("Remove group", lambda: self.command.emit(self.identity, "ungroup"), "ghost")
        )
        layout.addWidget(self.fields, 1)
        # Preserve descriptions from old files; no new standalone note cards are offered.
        self.imported_label = label("Imported workflow description")
        self.imported_notes = QTextEdit()
        self.imported_notes.setMinimumHeight(160)
        self.imported_notes.setAcceptRichText(False)
        self.imported_notes.setAccessibleName("Imported workflow description")
        layout.addWidget(self.imported_label)
        layout.addWidget(self.imported_notes, 1)
        self.imported_notes.textChanged.connect(self.update_imported)
        self.name.textChanged.connect(self.changed)
        self.color.currentIndexChanged.connect(self.changed)
        self.text.textChanged.connect(self.changed)
        self.select(None, None)

    def update_imported(self):
        visible = self.identity is None and bool(self.imported_notes.toPlainText())
        self.imported_label.setVisible(visible)
        self.imported_notes.setVisible(visible)

    def select(self, identity, metadata):
        if self.pending and identity == self.identity:
            return
        same_group = identity == self.identity
        self.timer.stop()
        self.loading = True
        self.identity = identity
        self.pending = False
        self.save.setEnabled(True)
        self.fields.setVisible(metadata is not None)
        self.hint.setText(
            "Click the group background or header to return here. Notes never affect playback."
            if metadata
            else "Select actions, press Ctrl+G, then click the colored rectangle to explain that section."
        )
        if metadata:
            if not same_group or self.name.text().strip() != metadata["name"]:
                self.name.setText(metadata["name"])
            index = self.color.findData(metadata["color"])
            if index < 0:
                self.color.addItem("Custom color", metadata["color"])
                index = self.color.count() - 1
            self.color.setCurrentIndex(index)
            notes = metadata.get("notes", "")
            # Saving synchronously refreshes this inspector with its own text.
            # Replacing an unchanged document resets its caret, selection, scroll
            # and native undo history, interrupting typing after every autosave.
            if not same_group or self.text.toPlainText() != notes:
                self.text.setPlainText(notes)
        self.loading = False
        if not same_group:
            # Reloading this longer hint during a save can briefly wrap it,
            # resize the text editor and clamp its scroll position.
            self.status.setText("Changes save automatically · Ctrl+Z to undo")
        self.update_imported()

    def changed(self, *_):
        if self.loading or self.identity is None:
            return
        self.pending = True
        valid = bool(self.name.text().strip()) and len(self.text.toPlainText()) <= 20000
        self.save.setEnabled(valid)
        self.status.setText(
            "Saving…" if valid else "Give the group a name and keep notes within 20,000 characters."
        )
        self.timer.start()
        self.draftChanged.emit()

    def flush(self):
        self.timer.stop()
        if not self.pending:
            return True
        if not self.name.text().strip() or len(self.text.toPlainText()) > 20000:
            return False
        self.pending = False  # Guard reentrant model/dirty notifications.
        self.applied.emit(
            self.identity,
            self.name.text().strip(),
            self.color.currentData(),
            self.text.toPlainText(),
        )
        self.status.setText("Saved · Ctrl+Z to undo")
        return True
