from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton

from .theme import icon


def button(text, callback, name="", tip="", glyph=None):
    widget = QPushButton(text.replace("&", "&&"))
    widget.setObjectName(name)
    widget.setToolTip(tip)
    if glyph:
        widget.setIcon(icon(glyph, "#201b2e" if name == "primary" else "#b6b0cd"))
    widget.clicked.connect(callback)
    return widget


def label(text, name="muted"):
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.PlainText)
    return widget
