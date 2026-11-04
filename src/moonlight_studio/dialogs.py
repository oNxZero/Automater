"""Studio dialogs with explicit actions, keyboard defaults and consistent spacing."""

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


class NoteDialog(QDialog):
    def __init__(self, parent, title="Note", text=""):
        super().__init__(parent)
        self.setWindowTitle("Workflow note")
        self.setMinimumSize(460, 360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(label("Explain this part of your workflow", "heading"))
        layout.addWidget(label("Notes are visual only. They never send input or add a delay."))
        self.title = QLineEdit(title)
        self.title.setMaxLength(120)
        self.title.setPlaceholderText("Note title")
        self.title.setAccessibleName("Note title")
        layout.addWidget(self.title)
        self.text = QTextEdit()
        self.text.setAcceptRichText(False)
        self.text.setPlainText(text)
        self.text.setPlaceholderText("What happens here? Include useful context or instructions…")
        self.text.setAccessibleName("Note text")
        layout.addWidget(self.text, 1)
        self.limit = label("")
        layout.addWidget(self.limit)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button("Cancel", self.reject, "ghost"))
        self.save = button("Save note", self.accept, "primary", glyph="check")
        self.save.setDefault(True)
        actions.addWidget(self.save)
        layout.addLayout(actions)
        self.text.textChanged.connect(self.validate_text)
        self.validate_text()

    def validate_text(self):
        count = len(self.text.toPlainText())
        self.limit.setText(f"{count:,} / 4,000 characters")
        self.save.setEnabled(count <= 4000)


class GroupDialog(NameDialog):
    def __init__(self, parent, name="", color="#b5a4fa"):
        super().__init__(
            parent,
            "Name this group",
            name,
            "Group selected actions visually. Their order and playback stay the same.",
            "Save group",
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
        self.color.setCurrentIndex(max(0, self.color.findData(color)))
        self.layout().insertWidget(self.layout().count() - 1, self.color)
