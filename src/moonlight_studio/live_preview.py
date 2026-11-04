"""A bounded live capture preview; it never changes the editable workflow."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QWidget

from .theme import COLORS, MUTED, TEXT, font, icon, paint_color
from .workflow import blocks_for, duration_text, friendly_key


class RecordingPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(166)
        self.count, self.elapsed = 0, 0.0
        self.held, self.displayed_blocks = [], []
        self.setAccessibleName("Live recording preview. Latest captured actions and held inputs.")
        self.hide()

    def set_snapshot(self, count, recent, held, elapsed):
        self.count, self.elapsed = count, max(0, elapsed)
        self.held = list(held)
        self.displayed_blocks = blocks_for(recent)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(paint_color("#3a3c52"), 1))
        painter.setBrush(paint_color("#1b1e2e"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        painter.setBrush(paint_color("#f2a3bc"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(14, 17, 7, 7))
        painter.setPen(paint_color(TEXT))
        painter.setFont(font(9, True))
        painter.drawText(
            QRectF(30, 8, self.width() - 44, 24),
            Qt.AlignVCenter,
            f"Recording · {self.elapsed:.1f}s · {self.count:,} events captured",
        )
        painter.setFont(font(8))
        painter.setPen(paint_color(MUTED))
        detail = (
            "Held: " + ", ".join(friendly_key(code) for code in self.held)
            if self.held
            else "Latest recorded actions · F6 finishes and adds them to your workflow"
        )
        painter.drawText(
            QRectF(14, 32, self.width() - 28, 20),
            Qt.AlignVCenter,
            painter.fontMetrics().elidedText(detail, Qt.ElideRight, self.width() - 28),
        )
        count = min(8, max(1, (self.width() - 28) // 150))
        width = (self.width() - 28 - (count - 1) * 8) / count
        for index, block in enumerate(self.displayed_blocks[-count:]):
            left = 14 + index * (width + 8)
            painter.setPen(QPen(paint_color("#363d52"), 1))
            painter.setBrush(paint_color("#232839"))
            painter.drawRoundedRect(QRectF(left, 60, width, 92), 9, 9)
            color = COLORS[block.kind]
            glyph = (
                "press"
                if block.title.startswith("Press ")
                else "release"
                if block.title.startswith("Release ")
                else block.kind
            )
            painter.drawPixmap(round(left + 10), 70, icon(glyph, color).pixmap(16, 16))
            painter.setFont(font(8, True))
            painter.setPen(paint_color(TEXT))
            painter.drawText(
                QRectF(left + 10, 91, width - 20, 22),
                Qt.AlignVCenter,
                painter.fontMetrics().elidedText(block.title, Qt.ElideRight, round(width - 20)),
            )
            painter.setFont(font(8))
            painter.setPen(paint_color(MUTED))
            painter.drawText(
                QRectF(left + 10, 121, width - 20, 19),
                Qt.AlignVCenter,
                f"{block.end - block.start} events · {duration_text(round(block.duration, 1))}",
            )
        if not self.displayed_blocks:
            painter.setPen(paint_color(MUTED))
            painter.drawText(
                QRectF(14, 70, self.width() - 28, 60),
                Qt.AlignCenter,
                "Waiting for your first input…",
            )
