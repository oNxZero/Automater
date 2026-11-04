"""Automater dialogs with explicit actions, keyboard defaults and consistent spacing."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLineEdit, QTextEdit, QVBoxLayout

from .widgets import button, label


class SaveChangesDialog(QDialog):
    def __init__(self, parent, name, path=None, count=0):
        super().__init__(parent)
        self.choice = "cancel"
        self.setWindowTitle("Save your workflow")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(18)
        layout.addWidget(label("Keep your changes?", "heading"))
        title = label(name, "body")
        title.setTextFormat(Qt.PlainText)
        layout.addWidget(title)
        layout.addWidget(
            label("Save this workflow before closing, or discard the changes from this session.")
        )
        detail = label(
            f"{count:,} workflow items · {path.name if path else 'Not saved to a file yet'}"
        )
        detail.setTextFormat(Qt.PlainText)
        layout.addWidget(detail)
        actions = QHBoxLayout()
        self.discard = button("Discard changes", lambda: self.finish("discard"), "ghost")
        self.cancel = button("Keep editing", self.reject, "ghost")
        self.save = button("Save workflow", lambda: self.finish("save"), "primary", glyph="save")
        self.save.setDefault(True)
        actions.addWidget(self.discard)
        actions.addStretch()
        actions.addWidget(self.cancel)
        actions.addWidget(self.save)
        layout.addLayout(actions)

    def finish(self, choice):
        self.choice = choice
        self.accept()

    @classmethod
    def ask(cls, parent, name, path=None, count=0):
        dialog = cls(parent, name, path, count)
        dialog.exec()
        return dialog.choice


class NameDialog(QDialog):
    def __init__(self, parent, title, value="", explanation="", confirm="Rename"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(label(title, "heading"))
        if explanation:
            layout.addWidget(label(explanation))
        self.name = QLineEdit(value)
        self.name.setMaxLength(120)
        self.name.setAccessibleName("Name")
        self.name.selectAll()
        layout.addWidget(self.name)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button("Cancel", self.reject, "ghost"))
        self.confirm = button(confirm, self.accept, "primary", glyph="check")
        self.confirm.setDefault(True)
        self.name.textChanged.connect(lambda text: self.confirm.setEnabled(bool(text.strip())))
        self.confirm.setEnabled(bool(value.strip()))
        actions.addWidget(self.confirm)
        layout.addLayout(actions)

    @classmethod
    def ask(cls, parent, title, value="", explanation="", confirm="Rename"):
        dialog = cls(parent, title, value, explanation, confirm)
        return dialog.name.text().strip() if dialog.exec() == QDialog.Accepted else None


class GroupDialog(NameDialog):
    def __init__(self, parent, name="", color="#b5a4fa", notes=""):
        super().__init__(
            parent,
            "Name this group",
            name,
            "Group selected actions visually. Their order and playback stay the same.",
            "Apply group",
        )
        self.color = QComboBox()
        self.color.setAccessibleName("Group color")
        for title, value in (
            ("Lavender", "#b5a4fa"),
            ("Blue", "#83b8f2"),
            ("Mint", "#75d6c0"),
            ("Amber", "#e8c58a"),
            ("Rose", "#f2a3bc"),
        ):
            self.color.addItem(title, value)
        if self.color.findData(color) < 0:
            self.color.addItem("Custom color", color)
        self.color.setCurrentIndex(self.color.findData(color))
        self.layout().insertWidget(self.layout().count() - 1, self.color)
        self.notes = QTextEdit()
        self.notes.setAcceptRichText(False)
        self.notes.setPlainText(notes)
        self.notes.setPlaceholderText("Explain the actions inside this rectangle…")
        self.notes.setAccessibleName("Notes for this group")
        self.notes.setMinimumHeight(160)
        self.layout().insertWidget(self.layout().count() - 1, label("Group notes"))
        self.layout().insertWidget(self.layout().count() - 1, self.notes)
        self.note_limit = label("")
        self.layout().insertWidget(self.layout().count() - 1, self.note_limit)
        self.notes.textChanged.connect(self.validate_notes)
        self.name.textChanged.connect(self.validate_notes)
        self.validate_notes()

    def validate_notes(self, *_):
        count = len(self.notes.toPlainText())
        self.note_limit.setText(f"{count:,} / 20,000 characters")
        self.confirm.setEnabled(bool(self.name.text().strip()) and count <= 20000)
