"""A bounded, interactive left-to-right view of the existing linear script."""

import math
from bisect import bisect_right
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .theme import COLORS, MUTED, TEXT, font, icon

PAGE_SIZE = 60
CARD_WIDTH, CARD_HEIGHT, PITCH = 204, 144, 260


def friendly_key(code):
    names = {
        "BTN_LEFT": "Left click",
        "BTN_RIGHT": "Right click",
        "BTN_MIDDLE": "Middle click",
        "KEY_LEFTCTRL": "Left Ctrl",
        "KEY_RIGHTCTRL": "Right Ctrl",
        "KEY_SPACE": "Space",
        "KEY_LEFTSHIFT": "Left Shift",
        "KEY_RIGHTSHIFT": "Right Shift",
        "KEY_ESC": "Esc",
        "KEY_ENTER": "Enter",
    }
    return names.get(code, code.removeprefix("KEY_").removeprefix("BTN_").replace("_", " ").title())


def duration_text(ms):
    return f"{ms / 1000:.2f} s" if ms >= 1000 else f"{ms:g} ms"


@dataclass(frozen=True)
class Block:
    start: int
    end: int  # Exclusive source-event range. Grouping never changes raw data.
    kind: str
    title: str
    detail: str
    duration: float
    enabled: bool


def blocks_for(steps):
    result, i = [], 0
    while i < len(steps):
        step, end = steps[i], i + 1
        duration = step.delay_ms
        if (
            step.action == "key_down"
            and end < len(steps)
            and steps[end].action == "key_up"
            and steps[end].code == step.code
            and steps[end].enabled == step.enabled
        ):
            end += 1
            duration += steps[i + 1].delay_ms
            mouse = step.code.startswith("BTN_")
            kind = "mouse" if mouse else "key"
            title = friendly_key(step.code) if mouse else f"Hold {friendly_key(step.code)}"
            detail = f"{'Hold' if mouse else 'Pressed for'} {duration_text(steps[i + 1].delay_ms)}"
        elif step.action in ("move", "scroll"):
            kind, dx, dy = step.action, step.x, step.y
            while (
                end < len(steps)
                and steps[end].action == kind
                and steps[end].enabled == step.enabled
            ):
                duration += steps[end].delay_ms
                dx, dy = dx + steps[end].x, dy + steps[end].y
                end += 1
            title = "Move pointer" if kind == "move" else "Scroll"
            detail = f"X {dx:+,}   Y {dy:+,}"
        elif step.action == "wait":
            kind, title = "wait", "Wait"
            detail = f"Pause for {duration_text(duration)}"
        else:
            kind = "mouse" if step.code.startswith("BTN_") else "key"
            title = (
                f"{'Press' if step.action == 'key_down' else 'Release'} {friendly_key(step.code)}"
            )
            detail = "Mouse button" if kind == "mouse" else "Keyboard input"
        result.append(Block(i, end, kind, title, detail, duration, step.enabled))
        i = end
    return result


class Node(QGraphicsObject):
    def __init__(self, block, index, canvas):
        super().__init__()
        self.block, self.index, self.canvas = block, index, canvas
        self.playing = False
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsFocusable)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)
        self.hovered = False
        self.setToolTip(
            f"{block.title}\nEvents {block.start + 1}–{block.end}\nClick to edit · drag horizontally to reorder"
        )

    def boundingRect(self):
        return QRectF(-5, -5, CARD_WIDTH + 10, CARD_HEIGHT + 15)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(COLORS[self.block.kind])
        rect = QRectF(0, 0, CARD_WIDTH, CARD_HEIGHT)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(5, 7, 15, 70))
        painter.drawRoundedRect(rect.translated(0, 6), 12, 12)
        gradient = QLinearGradient(0, 0, CARD_WIDTH, CARD_HEIGHT)
        gradient.setColorAt(0, QColor("#25283c" if self.isSelected() else "#222738"))
        gradient.setColorAt(1, QColor("#1c2030"))
        border = (
            color
            if self.isSelected() or self.playing
            else QColor("#55566f" if self.hovered else "#353b50")
        )
        painter.setPen(QPen(border, 2 if self.isSelected() or self.playing else 1))
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, 12, 12)
        if not self.block.enabled:
            painter.setOpacity(0.45)
        tint = QColor(color)
        tint.setAlpha(30)
        painter.setBrush(tint)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(16, 16, 33, 33), 9, 9)
        name = "mouse" if self.block.kind == "mouse" else self.block.kind
        painter.drawPixmap(22, 22, icon(name, color.name()).pixmap(21, 21))
        painter.setFont(font(8, True))
        painter.setPen(QColor(MUTED))
        painter.drawText(
            QRectF(58, 17, 126, 28),
            Qt.AlignVCenter | Qt.AlignRight,
            f"{self.index + 1:02d}  ·  {'SKIPPED' if not self.block.enabled else self.block.kind.upper()}",
        )
        painter.setFont(font(11, True))
        painter.setPen(QColor(TEXT))
        painter.drawText(QRectF(16, 62, 174, 24), Qt.AlignVCenter, self.block.title)
        painter.setFont(font(9))
        painter.setPen(QColor("#a0aac5"))
        painter.drawText(QRectF(16, 88, 174, 20), Qt.AlignVCenter, self.block.detail)
        painter.setPen(QPen(QColor("#32384c"), 1))
        painter.drawLine(16, 115, 188, 115)
        painter.setFont(font(8))
        painter.setPen(color)
        count = self.block.end - self.block.start
        painter.drawText(
            QRectF(16, 119, 120, 18),
            Qt.AlignVCenter,
            "Playing…" if self.playing else f"{count} event{'s' if count != 1 else ''}",
        )
        painter.setPen(QColor("#929bb6"))
        painter.drawText(
            QRectF(120, 119, 68, 18),
            Qt.AlignVCenter | Qt.AlignRight,
            duration_text(self.block.duration),
        )

    def hoverEnterEvent(self, event):
        self.hovered = True
        self.update()

    def hoverLeaveEvent(self, event):
        self.hovered = False
        self.update()

    def mousePressEvent(self, event):
        self.origin = event.scenePos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        delta = event.scenePos().x() - self.origin.x()
        if abs(delta) > 12:
            self.setPos(self.canvas.node_x(self.index) + delta, 136)
            self.setZValue(2)

    def mouseReleaseEvent(self, event):
        delta = event.scenePos().x() - self.origin.x()
        super().mouseReleaseEvent(event)
        self.setPos(self.canvas.node_x(self.index), 136)
        self.setZValue(0)
        if abs(delta) > PITCH / 2:
            target = max(0, min(len(self.canvas.blocks) - 1, self.index + round(delta / PITCH)))
            if target != self.index:
                self.canvas.reorderRequested.emit(self.index, target)

    def contextMenuEvent(self, event):
        self.setSelected(True)
        menu = QMenu()
        for text, action in (
            ("Duplicate action", "duplicate"),
            ("Enable / disable", "toggle"),
            ("Move left", "left"),
            ("Move right", "right"),
            ("Delete action", "delete"),
        ):
            item = menu.addAction(text)
            item.triggered.connect(
                lambda checked=False, name=action: self.canvas.command.emit(name)
            )
        menu.exec(event.screenPos())


class InsertPoint(QGraphicsObject):
    def __init__(self, canvas, row):
        super().__init__()
        self.canvas, self.row = canvas, row
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Insert an action here")

    def boundingRect(self):
        return QRectF(-11, -11, 22, 22)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#49506b"), 1))
        painter.setBrush(QColor("#202638"))
        painter.drawEllipse(QPointF(0, 0), 10, 10)
        painter.setPen(QPen(QColor("#b1a5d4"), 1.4))
        painter.drawLine(-4, 0, 4, 0)
        painter.drawLine(0, -4, 0, 4)

    def mousePressEvent(self, event):
        self.canvas.insertRequested.emit(self.row)
        event.accept()


class Canvas(QGraphicsView):
    selected = Signal(object)
    insertRequested = Signal(int)
    reorderRequested = Signal(int, int)
    command = Signal(str)
    zoomChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setAccessibleName(
            "Left to right workflow canvas. Select actions to edit. Control plus wheel zooms."
        )
        self.blocks, self.starts, self.nodes = [], [], {}
        self.page = 0
        self.scene().selectionChanged.connect(self.selection_changed)

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor("#131724"))
        painter.setPen(QPen(QColor("#293044"), 1))
        spacing = 24
        left, top = (
            math.floor(rect.left() / spacing) * spacing,
            math.floor(rect.top() / spacing) * spacing,
        )
        for x in range(left, math.ceil(rect.right()), spacing):
            for y in range(top, math.ceil(rect.bottom()), spacing):
                painter.drawPoint(QPointF(x, y))

    def node_x(self, index):
        return 136 + (index - self.page * PAGE_SIZE) * PITCH

    def rebuild(self, blocks, selected_row=-1):
        self.blocks = blocks
        self.starts = [b.start for b in blocks]
        self.page = min(self.page, max(0, (len(blocks) - 1) // PAGE_SIZE))
        if selected_row >= 0:
            self.page = max(0, bisect_right(self.starts, selected_row) - 1) // PAGE_SIZE
        self.render_page()
        if selected_row >= 0:
            self.select_row(selected_row, reveal=False)

    def render_page(self):
        self.scene().blockSignals(True)
        self.scene().clear()
        self.nodes = {}
        start = self.page * PAGE_SIZE
        visible = self.blocks[start : start + PAGE_SIZE]
        for offset, block in enumerate(visible):
            index = start + offset
            node = Node(block, index, self)
            node.setPos(self.node_x(index), 136)
            self.scene().addItem(node)
            self.nodes[index] = node
        for i in range(len(visible) + 1):
            x1 = 60 if i == 0 else 136 + (i - 1) * PITCH + CARD_WIDTH
            x2 = 136 + i * PITCH if i < len(visible) else x1 + 80
            path = QPainterPath(QPointF(x1, 208))
            path.lineTo(x2, 208)
            self.scene().addPath(path, QPen(QColor("#4a4c67"), 1.5))
            arrow = QPainterPath(QPointF(x2 - 5, 204))
            arrow.lineTo(x2, 208)
            arrow.lineTo(x2 - 5, 212)
            self.scene().addPath(arrow, QPen(QColor("#6f6b8f"), 1.5))
            row = visible[i].start if i < len(visible) else visible[-1].end if visible else 0
            point = InsertPoint(self, row)
            point.setPos((x1 + x2) / 2, 208)
            self.scene().addItem(point)
        for title, x in (
            ("START" if not self.page else "CONTINUED", 28),
            (
                "FINISH" if start + len(visible) == len(self.blocks) else "NEXT PAGE",
                136 + max(0, len(visible) - 1) * PITCH + CARD_WIDTH + 47,
            ),
        ):
            text = self.scene().addSimpleText(title, font(7, True))
            text.setBrush(QColor(MUTED))
            text.setPos(x, 246)
        width = 136 + max(0, len(visible) - 1) * PITCH + CARD_WIDTH + 140
        self.scene().setSceneRect(0, 0, width, 420)
        self.scene().blockSignals(False)

    def selection_changed(self):
        nodes = [item for item in self.scene().selectedItems() if isinstance(item, Node)]
        self.selected.emit(nodes[0].block if nodes else None)

    def select_row(self, row, reveal=True):
        if row < 0 or not self.blocks:
            return
        index = max(0, bisect_right(self.starts, row) - 1)
        if index // PAGE_SIZE != self.page:
            self.page = index // PAGE_SIZE
            self.render_page()
        self.scene().blockSignals(True)
        self.scene().clearSelection()
        node = self.nodes.get(index)
        if node:
            node.setSelected(True)
            if reveal:
                self.ensureVisible(node, 60, 50)
        self.scene().blockSignals(False)

    def highlight(self, row):
        if row >= 0:
            index = max(0, bisect_right(self.starts, row) - 1)
            if index // PAGE_SIZE != self.page:
                self.page = index // PAGE_SIZE
                self.render_page()
        else:
            index = -1
        for key, node in self.nodes.items():
            if node.playing != (key == index):
                node.playing = key == index
                node.update()
        if index in self.nodes:
            self.ensureVisible(self.nodes[index], 60, 50)

    def zoom(self, factor):
        current = self.transform().m11()
        target = max(0.5, min(1.6, current * factor))
        self.scale(target / current, target / current)
        self.zoomChanged.emit(round(target * 100))

    def fit(self):
        count = min(PAGE_SIZE, len(self.blocks) - self.page * PAGE_SIZE)
        width = 136 + max(0, count - 1) * PITCH + CARD_WIDTH + 140
        scale = max(0.6, min(1, (self.viewport().width() - 24) / width))
        self.resetTransform()
        self.scale(scale, scale)
        self.horizontalScrollBar().setValue(0)
        self.zoomChanged.emit(round(scale * 100))

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.zoom(1.12 if event.angleDelta().y() > 0 else 1 / 1.12)
        elif event.angleDelta().x() or event.modifiers() & Qt.ShiftModifier:
            super().wheelEvent(event)
        else:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - event.angleDelta().y())
        event.accept()

    def keyPressEvent(self, event):
        command = {
            Qt.Key_Delete: "delete",
            Qt.Key_Backspace: "delete",
            Qt.Key_Left: "select_left",
            Qt.Key_Right: "select_right",
        }.get(event.key())
        if command and event.modifiers() & Qt.AltModifier:
            command = {"select_left": "left", "select_right": "right"}.get(command, command)
        if command:
            self.command.emit(command)
        else:
            super().keyPressEvent(event)


class Workflow(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = Canvas()
        layout.addWidget(self.canvas, 1)
        footer = QHBoxLayout()
        footer.setContentsMargins(14, 8, 14, 8)
        self.page_label = QLabel("Actions run from left to right")
        self.page_label.setObjectName("muted")
        footer.addWidget(self.page_label)
        self.previous = QPushButton("Previous")
        self.next = QPushButton("Next")
        for widget, delta in ((self.previous, -1), (self.next, 1)):
            widget.setObjectName("ghost")
            widget.clicked.connect(lambda checked=False, d=delta: self.change_page(d))
            footer.addWidget(widget)
        footer.addStretch()
        for name, tip, callback in (
            ("minus", "Zoom out", lambda: self.canvas.zoom(1 / 1.2)),
            ("plus", "Zoom in", lambda: self.canvas.zoom(1.2)),
            ("fit", "Fit workflow", self.canvas.fit),
        ):
            btn = QPushButton()
            btn.setObjectName("ghost")
            btn.setIcon(icon(name))
            btn.setToolTip(tip)
            btn.setAccessibleName(tip)
            btn.clicked.connect(callback)
            footer.addWidget(btn)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("muted")
        footer.addWidget(self.zoom_label)
        self.canvas.zoomChanged.connect(lambda value: self.zoom_label.setText(f"{value}%"))
        layout.addLayout(footer)
        self.update_footer()

    def update_footer(self):
        count = len(self.canvas.blocks)
        self.previous.setVisible(count > PAGE_SIZE)
        self.next.setVisible(count > PAGE_SIZE)
        self.previous.setEnabled(self.canvas.page > 0)
        self.next.setEnabled((self.canvas.page + 1) * PAGE_SIZE < count)
        self.page_label.setText(
            f"{count:,} actions · drag to reorder · scroll to explore"
            if count <= PAGE_SIZE
            else f"Actions {self.canvas.page * PAGE_SIZE + 1:,}–{min(count, (self.canvas.page + 1) * PAGE_SIZE):,} of {count:,}"
        )

    def change_page(self, delta):
        page = self.canvas.page + delta
        if 0 <= page <= (len(self.canvas.blocks) - 1) // PAGE_SIZE:
            self.canvas.page = page
            self.canvas.render_page()
            self.canvas.horizontalScrollBar().setValue(0)
            self.update_footer()
            self.canvas.selected.emit(self.canvas.blocks[page * PAGE_SIZE])
