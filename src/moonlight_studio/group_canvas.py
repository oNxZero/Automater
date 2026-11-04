"""Viewport-local visual group frames. Grouping never changes event order."""

import html
from bisect import bisect_right

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsObject, QMenu

from .theme import font


class GroupFrame(QGraphicsObject):
    def __init__(self, canvas, identity, metadata, rect, first):
        super().__init__()
        self.canvas, self.identity, self.metadata = canvas, identity, metadata
        self.first = first
        self.rect = QRectF(0, 0, rect.width(), rect.height())
        self.setPos(rect.topLeft())
        self.setZValue(-2)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(
            "<qt>" + html.escape(metadata["name"]) + " · click the header to select this group</qt>"
        )

    def boundingRect(self):
        return self.rect.adjusted(-2, -2, 2, 2)

    def shape(self):
        path = QPainterPath()
        path.addRect(QRectF(0, 0, self.rect.width(), 28))
        return path  # Empty space below still supports desktop-style box selection.

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(self.metadata["color"])
        border = QColor(color)
        border.setAlpha(130)
        tint = QColor(color)
        tint.setAlpha(9)
        painter.setPen(QPen(border, 1.25))
        painter.setBrush(tint)
        painter.drawRoundedRect(self.rect, 14, 14)
        painter.setFont(font(9, True))
        painter.setPen(color)
        painter.drawText(
            QRectF(14, 2, self.rect.width() - 28, 24),
            Qt.AlignVCenter,
            painter.fontMetrics().elidedText(
                self.metadata["name"], Qt.ElideRight, round(self.rect.width() - 28)
            ),
        )

    def mousePressEvent(self, event):
        self.canvas.anchor = self.first
        self.canvas.groupRequested.emit(self.identity, "select")
        event.accept()

    def contextMenuEvent(self, event):
        self.canvas.anchor = self.first
        menu = QMenu()
        for title, action in (
            ("Select group", "select"),
            ("Rename / change color…", "edit"),
            ("Ungroup actions", "ungroup"),
        ):
            menu.addAction(
                title,
                lambda checked=False, name=action: self.canvas.groupRequested.emit(
                    self.identity, name
                ),
            )
        menu.exec(event.screenPos())
        event.accept()


class GroupCanvasMixin:
    def build_group_spans(self):
        self.group_spans = []
        for index, block in enumerate(self.blocks):
            if not block.group_id:
                continue
            if (
                self.group_spans
                and self.group_spans[-1][2] == block.group_id
                and self.group_spans[-1][1] == index
            ):
                first, _, identity = self.group_spans[-1]
                self.group_spans[-1] = (first, index + 1, identity)
            else:
                self.group_spans.append((index, index + 1, block.group_id))
        self.group_starts = [span[0] for span in self.group_spans]

    def update_group_frames(self, wanted):
        from .workflow import CARD_HEIGHT, CARD_WIDTH

        frames = {}
        for index in wanted:
            at = bisect_right(self.group_starts, index) - 1
            if at < 0:
                continue
            first, end, identity = self.group_spans[at]
            if index >= end or identity not in self.groups:
                continue
            if self.layout_mode == "grid":
                row = index // self.grid_columns
                first, end = (
                    max(first, row * self.grid_columns),
                    min(end, (row + 1) * self.grid_columns),
                )
            # A long horizontal group retains one continuous border across the canvas.
            start_pos, end_pos = self.node_position(first), self.node_position(end - 1)
            key = (identity, first, end)
            frames[key] = QRectF(
                start_pos.x() - 14,
                start_pos.y() - 32,
                end_pos.x() - start_pos.x() + CARD_WIDTH + 28,
                end_pos.y() - start_pos.y() + CARD_HEIGHT + 46,
            )
        for key in set(self.group_items) - frames.keys():
            self.remove_scene_item(self.group_items.pop(key))
        for key in frames.keys() - self.group_items.keys():
            item = GroupFrame(self, key[0], self.groups[key[0]], frames[key], key[1])
            self.scene().addItem(item)
            self.group_items[key] = item
