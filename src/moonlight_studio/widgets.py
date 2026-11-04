from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QTabBar

from .theme import icon


class ElidedLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.full_text = text
        self.setWordWrap(False)
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setMinimumWidth(80)
        self.setText(text)

    def setText(self, text):
        self.full_text = text
        self.setToolTip(text)
        super().setText(self.fontMetrics().elidedText(text, Qt.ElideRight, max(80, self.width())))

    def sizeHint(self):
        return QSize(
            min(420, self.fontMetrics().horizontalAdvance(self.full_text) + 10),
            self.fontMetrics().height() + 4,
        )

    def minimumSizeHint(self):
        return QSize(80, self.fontMetrics().height() + 4)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setText(self.full_text)


class WindowTargetButton(QPushButton):
    def __init__(self, callback):
        super().__init__()
        self.caption = "Choose open window…"
        self.setIcon(icon("target"))
        self.setIconSize(QSize(20, 20))
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumHeight(36)
        self.setAccessibleName("Choose an open application window")
        self.clicked.connect(callback)
        self.set_caption(self.caption)

    def set_caption(self, caption):
        self.caption = caption
        self.setToolTip(caption)
        self.setText(
            self.fontMetrics()
            .elidedText(caption, Qt.ElideRight, max(20, self.width() - 58))
            .replace("&", "&&")
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.set_caption(self.caption)


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
        widget.setProperty("themeGlyph", glyph)
        widget.setProperty("themeTone", name)
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
