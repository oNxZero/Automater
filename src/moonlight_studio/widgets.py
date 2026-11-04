from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QLabel, QPushButton

from .theme import icon


def button(text, callback, name="", tip="", glyph=None):
    widget = QPushButton(text.replace("&", "&&"))
    widget.setObjectName(name)
    widget.setToolTip(tip)
    if not text:
        widget.setFixedWidth(36)
        widget.setAccessibleName(tip)
    if glyph:
        widget.setIcon(
            icon(
                glyph,
                "#201b2e"
                if name == "primary"
                else "#f2a3bc"
                if name in ("record", "stop")
                else "#b6b0cd",
            )
        )
        widget.setIconSize(QSize(20, 20))
    widget.clicked.connect(callback)
    return widget


def label(text, name="muted"):
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.PlainText)
    return widget
