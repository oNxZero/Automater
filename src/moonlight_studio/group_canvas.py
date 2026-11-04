"""One colored rectangle per group; its background opens its notes."""

import html

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsObject, QMenu

from .theme import font, legible_group_color, paint_color


class GroupFrame(QGraphicsObject):
    def __init__(self, canvas, identity, metadata, rect, first):
        super().__init__()
        from .workflow import CARD_WIDTH

        self.canvas, self.identity, self.metadata, self.first = canvas, identity, metadata, first
        self.rect = QRectF(0, 0, rect.width(), rect.height())
        # Groups wrapping across grid rows can share their outer top-left corner.
        # Anchor each heading above its own first card so labels remain distinct.
        self.header = QRectF(canvas.node_position(first).x() - rect.left(), 2, CARD_WIDTH, 24)
        self.setPos(rect.topLeft())
        self.setZValue(-2)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(
            "<qt>" + html.escape(metadata["name"]) + " · click the rectangle to open its notes</qt>"
        )

    def boundingRect(self):
        return self.rect.adjusted(-2, -2, 2, 2)

    def shape(self):
        path = QPainterPath()
        path.addRoundedRect(self.rect, 12, 12)
        return path

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(self.metadata["color"])
        border, tint = legible_group_color(self.metadata["color"]), QColor(color)
        border.setAlpha(175)
        tint.setAlpha(28)
        painter.setPen(QPen(border, 1.5))
        painter.setBrush(tint)
        painter.drawRoundedRect(self.rect, 12, 12)
        painter.setPen(Qt.NoPen)
        painter.setBrush(paint_color("#1c2032"))
        painter.drawRoundedRect(self.header, 5, 5)
        painter.setFont(font(9, True))
        painter.setPen(legible_group_color(self.metadata["color"]))
        painter.drawText(
            self.header.adjusted(7, 0, -60, 0),
            Qt.AlignVCenter,
            painter.fontMetrics().elidedText(
                self.metadata["name"], Qt.ElideRight, max(20, round(self.header.width() - 67))
            ),
        )
        painter.setFont(font(8))
        painter.drawText(
            QRectF(self.header.right() - 55, 2, 48, 24),
            Qt.AlignRight | Qt.AlignVCenter,
            "Notes" if self.metadata.get("notes") else "+ Notes",
        )

    def mousePressEvent(self, event):
        # Let the view handle rubber-band selection. A click without a drag is
        # recognized after release, so group backgrounds never swallow box selection.
        event.ignore()

    def contextMenuEvent(self, event):
        self.canvas.anchor = self.first
        menu = QMenu()
        for title, action in (
            ("Open group notes", "inspect"),
            ("Select group actions", "select"),
            ("Remove group", "ungroup"),
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
        self.group_members = {}
        for index, block in enumerate(self.blocks):
            if block.group_id:
                self.group_members.setdefault(block.group_id, []).append(index)

    def calculate_group_rects(self):
        from .workflow import CARD_HEIGHT, CARD_WIDTH, PITCH

        self.group_rects = {}
        for identity, indices in self.group_members.items():
            if self.layout_mode == "grid":
                columns = [index % self.grid_columns for index in indices]
                a = QPointF(
                    136 + min(columns) * PITCH, 136 + (indices[0] // self.grid_columns) * 224
                )
                b = QPointF(
                    136 + max(columns) * PITCH, 136 + (indices[-1] // self.grid_columns) * 224
                )
            else:
                a, b = self.node_position(indices[0]), self.node_position(indices[-1])
            self.group_rects[identity] = QRectF(
                a.x() - 14,
                a.y() - 32,
                b.x() - a.x() + CARD_WIDTH + 28,
                b.y() - a.y() + CARD_HEIGHT + 46,
            )

    def update_group_frames(self, wanted):
        visible = (
            self.mapToScene(self.viewport().rect()).boundingRect().adjusted(-280, -250, 280, 250)
        )
        frames = {
            key: rect
            for key, rect in self.group_rects.items()
            if rect.intersects(visible) and key in self.groups
        }
        for key in set(self.group_items) - frames.keys():
            self.remove_scene_item(self.group_items.pop(key))
        for key in frames.keys() - self.group_items.keys():
            item = GroupFrame(self, key, self.groups[key], frames[key], self.group_members[key][0])
            self.scene().addItem(item)
            self.group_items[key] = item

    def group_at(self, position):
        for identity, item in self.group_items.items():
            if item.header.translated(item.pos()).contains(position):
                return identity
        candidates = [
            (rect.width() * rect.height(), key)
            for key, rect in self.group_rects.items()
            if rect.contains(position)
        ]
        return min(candidates)[1] if candidates else None
