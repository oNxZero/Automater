from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter

from .models import KEY_CODES
from .workflow import friendly_key


class KeyPicker(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMinimumContentsLength(10)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMaxVisibleItems(14)
        for code in sorted(KEY_CODES, key=lambda c: (c.startswith("BTN_"), friendly_key(c))):
            self.addItem(f"{friendly_key(code)} · {code}", code)
        self.completer().setCaseSensitivity(Qt.CaseInsensitive)
        self.completer().setFilterMode(Qt.MatchContains)
        self.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.lineEdit().setPlaceholderText("Search any key or button…")
        self.setAccessibleName("Search keyboard keys and mouse buttons")

    def set_code(self, code):
        self.setCurrentIndex(max(0, self.findData(code)))

    def code(self):
        text = self.currentText().strip()
        if self.currentIndex() >= 0 and self.itemText(self.currentIndex()) == text:
            return self.currentData()
        raw = text.upper().replace(" ", "_")
        for candidate in (raw, "KEY_" + raw, "BTN_" + raw):
            if candidate in KEY_CODES:
                return candidate
        matches = [code for code in KEY_CODES if friendly_key(code).lower() == text.lower()]
        if len(matches) == 1:
            return matches[0]
        raise ValueError("Choose a key or button from the search results")
