from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import QLabel, QPushButton, QTabBar

from .theme import icon


class WorkflowTabBar(QTabBar):
    """Inset native close widgets inside the painted tab, including its gap."""

    def tabLayoutChange(self):
        super().tabLayoutChange()
        if not getattr(self, "_close_layout_pending", False):
            self._close_layout_pending = True
            QTimer.singleShot(0, self, self.place_close_buttons)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.place_close_buttons()

    def place_close_buttons(self):
        self._close_layout_pending = False
        for index in range(self.count()):
            button = self.tabButton(index, QTabBar.RightSide)
            if button is not None:
                rect = self.tabRect(index)
                button.move(
                    rect.right() - 5 - 8 - button.width() + 1,
                    rect.top() + (rect.height() - button.height()) // 2,
                )


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
