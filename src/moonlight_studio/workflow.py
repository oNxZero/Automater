"""A bounded, interactive left-to-right view of the existing linear script."""

import math
from bisect import bisect_right
from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
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

from .editor import editing_command
from .run_feedback import block_state
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


def timing_range(low, high):
    if low == high:
        return duration_text(low)
    if high < 1000:
        return f"{low:.3g}–{high:.3g} ms"
    return f"{low / 1000:.3g}–{high / 1000:.3g} s"


@dataclass(frozen=True)
class Block:
    start: int
    end: int  # Exclusive source-event range. Grouping never changes raw data.
    kind: str
    title: str
    detail: str
    duration: float
    enabled: bool
    duration_max: float = 0


def blocks_for(steps):
    result, i = [], 0
    while i < len(steps):
        step, end = steps[i], i + 1
        duration = step.delay_ms
        if (
            not step.standalone
            and step.action == "key_down"
            and end < len(steps)
            and not steps[end].standalone
            and steps[end].action == "key_up"
            and steps[end].code == step.code
            and steps[end].enabled == step.enabled
        ):
            end += 1
            duration += steps[i + 1].delay_ms
            mouse = step.code.startswith("BTN_")
            kind = "mouse" if mouse else "key"
            title = friendly_key(step.code) if mouse else f"Hold {friendly_key(step.code)}"
            detail = f"{'Hold' if mouse else 'Pressed for'} {timing_range(steps[i + 1].delay_ms, steps[i + 1].maximum_ms)}"
        elif step.action in ("move", "scroll"):
            kind, dx, dy = step.action, step.x, step.y
            while (
                end < len(steps)
                and not step.standalone
                and not steps[end].standalone
                and steps[end].action == kind
                and steps[end].enabled == step.enabled
            ):
                duration += steps[end].delay_ms
                dx, dy = dx + steps[end].x, dy + steps[end].y
                end += 1
            title = "Move pointer" if kind == "move" else "Scroll"
            detail = f"X {dx:+,}   Y {dy:+,}"
        elif step.action == "wait":
            kind, title = "wait", "Timer"
            detail = f"Wait {timing_range(duration, step.maximum_ms)}"
        else:
            kind = "mouse" if step.code.startswith("BTN_") else "key"
            title = (
                f"{'Press' if step.action == 'key_down' else 'Release'} {friendly_key(step.code)}"
            )
            detail = "Mouse button" if kind == "mouse" else "Keyboard input"
        result.append(
            Block(
                i,
                end,
                kind,
                title,
                detail,
                duration,
                step.enabled,
                sum(s.maximum_ms for s in steps[i:end]),
            )
        )
        i = end
    return result


class Node(QGraphicsObject):
    def __init__(self, block, index, canvas):
        super().__init__()
        self.block, self.index, self.canvas = block, index, canvas
        self.playing = False
        self.execution_state = ""
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsFocusable)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)
        self.hovered = False
        self.emphasis = 0.0
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(140)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.valueChanged.connect(self.animate_emphasis)
        self.setToolTip(
            f"{block.title}\nEvents {block.start + 1}–{block.end}\nClick to edit · drag horizontally to reorder"
        )

    def boundingRect(self):
        return QRectF(-5, -5, CARD_WIDTH + 10, CARD_HEIGHT + 15)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(
            {
                "completed": "#75d6c0",
                "last": "#83b8f2",
                "stopped": "#e8c58a",
                "failed": "#f2a3bc",
            }.get(self.execution_state, COLORS[self.block.kind])
        )
        rect = QRectF(0, 0, CARD_WIDTH, CARD_HEIGHT)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(5, 7, 15, 70))
        painter.drawRoundedRect(rect.translated(0, 6), 12, 12)
        gradient = QLinearGradient(0, 0, CARD_WIDTH, CARD_HEIGHT)
        gradient.setColorAt(0, QColor("#25283c" if self.isSelected() else "#222738"))
        gradient.setColorAt(1, QColor("#1c2030"))
        border = (
            color
            if self.isSelected() or self.playing or self.execution_state
            else QColor("#55566f" if self.hovered else "#353b50")
        )
        painter.setPen(QPen(border, 2 if self.isSelected() or self.playing else 1))
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, 12, 12)
        if self.emphasis:
            glow = QColor(color)
            glow.setAlpha(round(22 * self.emphasis))
            painter.setBrush(glow)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 12, 12)
        if not self.block.enabled:
            painter.setOpacity(0.45)
        tint = QColor(color)
        tint.setAlpha(30)
        painter.setBrush(tint)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(16, 16, 33, 33), 9, 9)
        name = "mouse" if self.block.kind == "mouse" else self.block.kind
        if self.block.title.startswith("Press "):
            name = "press"
        elif self.block.title.startswith("Release "):
            name = "release"
        painter.drawPixmap(22, 22, icon(name, color.name()).pixmap(21, 21))
        painter.setFont(font(8, True))
        painter.setPen(QColor(MUTED))
        painter.drawText(
            QRectF(58, 17, 126, 28),
            Qt.AlignVCenter | Qt.AlignRight,
            f"{self.index + 1:02d}  ·  {self.execution_state.upper() if self.execution_state else 'SKIPPED' if not self.block.enabled else self.block.kind.upper()}",
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
            QRectF(16, 119, 70, 18),
            Qt.AlignVCenter,
            "Playing…" if self.playing else f"{count} event{'s' if count != 1 else ''}",
        )
        painter.setPen(QColor("#929bb6"))
        painter.drawText(
            QRectF(78, 119, 110, 18),
            Qt.AlignVCenter | Qt.AlignRight,
            timing_range(self.block.duration, self.block.duration_max),
        )

    def hoverEnterEvent(self, event):
        self.hovered = True
        self.transition()

    def hoverLeaveEvent(self, event):
        self.hovered = False
        self.transition()

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == QGraphicsItem.ItemSelectedHasChanged and hasattr(self, "animation"):
            self.transition()
        return result

    def transition(self):
        self.animation.stop()
        self.animation.setStartValue(self.emphasis)
        self.animation.setEndValue(1.0 if self.hovered or self.isSelected() else 0.0)
        self.animation.start()

    def animate_emphasis(self, value):
        self.emphasis = value
        self.update()

    def mousePressEvent(self, event):
        self.origin = event.scenePos()
        ids = set(self.canvas.selected_indices)
        mods = event.modifiers()
        self.collapse_on_click = self.index in ids and len(ids) > 1 and not mods
        if mods & Qt.ShiftModifier:
            anchor = self.canvas.anchor if self.canvas.anchor is not None else self.index
            selected = set(range(min(anchor, self.index), max(anchor, self.index) + 1))
            self.canvas.choose_indices(ids | selected if mods & Qt.ControlModifier else selected)
        elif mods & Qt.ControlModifier:
            self.canvas.choose_indices(ids ^ {self.index})
            self.canvas.anchor = self.index
        elif not self.collapse_on_click:
            self.canvas.choose_indices({self.index})
            self.canvas.anchor = self.index
        self.drag_origins = {
            i: node.pos()
            for i, node in self.canvas.nodes.items()
            if i in self.canvas.selected_indices
        }
        self.setFocus(Qt.MouseFocusReason)
        event.accept()

    def mouseMoveEvent(self, event):
        delta = event.scenePos() - self.origin
        if abs(delta.x()) + abs(delta.y()) > 10:
            for index, origin in self.drag_origins.items():
                self.canvas.nodes[index].setPos(origin + delta)
                self.canvas.nodes[index].setZValue(2)
        event.accept()

    def mouseReleaseEvent(self, event):
        delta = event.scenePos() - self.origin
        for index, origin in self.drag_origins.items():
            if index in self.canvas.nodes:
                self.canvas.nodes[index].setPos(origin)
                self.canvas.nodes[index].setZValue(0)
        event.accept()
        if abs(delta.x()) + abs(delta.y()) > 60 and self.canvas.nodes:
            destination = self.canvas.node_position(self.index) + delta
            target = min(
                self.canvas.nodes,
                key=lambda i: (self.canvas.node_position(i) - destination).manhattanLength(),
            )
            if target != self.index:
                self.canvas.reorderRequested.emit(self.index, target)
        elif self.collapse_on_click:
            self.canvas.choose_indices({self.index})

    def contextMenuEvent(self, event):
        if self.index not in self.canvas.selected_indices:
            self.canvas.choose_indices({self.index})
        menu = QMenu()
        for text, action in (
            ("Copy\tCtrl+C", "copy"),
            ("Cut\tCtrl+X", "cut"),
            ("Paste after selection\tCtrl+V", "paste"),
            ("Duplicate\tCtrl+D", "duplicate"),
            ("Select all\tCtrl+A", "select_all"),
            ("Randomize timing…", "randomize"),
            ("Use fixed timing", "fixed_timing"),
            ("Re-record selected actions…", "rerecord"),
            ("Show pointer path…", "preview_pointer"),
            ("Enable / disable", "toggle"),
            ("Split holds into press / release", "split"),
            ("Move earlier\tAlt+←", "left"),
            ("Move later\tAlt+→", "right"),
            ("Delete\tDelete", "delete"),
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


class StartPoint(QGraphicsObject):
    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Starting countdown and loop cursor position · click to configure")

    def boundingRect(self):
        return QRectF(-55, -24, 110, 75)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#28273d"))
        painter.setPen(QPen(QColor("#8e7abb"), 1.5))
        painter.drawEllipse(QPointF(0, 0), 20, 20)
        painter.drawPixmap(-10, -10, icon("target", "#c5b7ed").pixmap(20, 20))
        painter.setPen(QColor(MUTED))
        painter.setFont(font(8, True))
        painter.drawText(QRectF(-55, 26, 110, 20), Qt.AlignCenter, self.canvas.start_label)

    def mousePressEvent(self, event):
        self.canvas.command.emit("start_settings")
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
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.pan_origin = None
        self.pointer_interaction = False
        self.reveal_requested = False
        self.reveal_queued = False
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setAccessibleName(
            "Workflow. Left-drag empty space to box select. Middle-drag to pan. Ctrl-click adds selection."
        )
        self.blocks, self.starts, self.nodes = [], [], {}
        self.selected_indices = set()
        self.anchor = None
        self.page = 0
        self.layout_mode = "horizontal"
        self.start_label = "START"
        self.execution_states = {}
        self.execution_trace = None
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

    def node_position(self, index):
        i = index - self.page * PAGE_SIZE
        if self.layout_mode == "vertical":
            return QPointF(136, 110 + i * 214)
        if self.layout_mode == "grid":
            return QPointF(136 + (i % 4) * PITCH, 136 + (i // 4) * 224)
        return QPointF(136 + i * PITCH, 136)

    def node_x(self, index):
        return self.node_position(index).x()

    def rebuild(self, blocks, selected_row=-1):
        self.blocks = blocks
        self.starts = [b.start for b in blocks]
        self.page = min(self.page, max(0, (len(blocks) - 1) // PAGE_SIZE))
        self.selected_indices = set()
        if selected_row >= 0 and blocks:
            index = max(0, bisect_right(self.starts, selected_row) - 1)
            self.selected_indices = {index}
            self.page = index // PAGE_SIZE
        self.render_page()

    def render_page(self):
        self.scene().blockSignals(True)
        self.scene().clear()
        self.nodes = {}
        start = self.page * PAGE_SIZE
        visible = self.blocks[start : start + PAGE_SIZE]
        for offset, block in enumerate(visible):
            index = start + offset
            node = Node(block, index, self)
            node.setPos(self.node_position(index))
            node.setSelected(index in self.selected_indices)
            node.execution_state = self.execution_states.get(index, "")
            node.playing = node.execution_state == "running"
            self.scene().addItem(node)
            self.nodes[index] = node
        first = self.node_position(start)
        vertical = self.layout_mode == "vertical"
        start_pos = first + (
            QPointF(CARD_WIDTH / 2, -65) if vertical else QPointF(-76, CARD_HEIGHT / 2)
        )
        marker = StartPoint(self)
        marker.setPos(start_pos)
        self.scene().addItem(marker)
        for offset in range(len(visible) + 1):
            previous = self.node_position(start + offset - 1) if offset else None
            next_pos = self.node_position(start + offset) if offset < len(visible) else None
            if vertical:
                a = (
                    previous + QPointF(CARD_WIDTH / 2, CARD_HEIGHT)
                    if previous
                    else start_pos + QPointF(0, 20)
                )
                b = next_pos + QPointF(CARD_WIDTH / 2, 0) if next_pos else a + QPointF(0, 75)
            else:
                a = (
                    previous + QPointF(CARD_WIDTH, CARD_HEIGHT / 2)
                    if previous
                    else start_pos + QPointF(20, 0)
                )
                b = next_pos + QPointF(0, CARD_HEIGHT / 2) if next_pos else a + QPointF(80, 0)
            path = QPainterPath(a)
            wrapping = (
                self.layout_mode == "grid" and offset and offset % 4 == 0 and next_pos is not None
            )
            if wrapping:
                a = previous + QPointF(CARD_WIDTH / 2, CARD_HEIGHT)
                b = next_pos + QPointF(CARD_WIDTH / 2, 0)
                path = QPainterPath(a)
                middle_y = (a.y() + b.y()) / 2
                radius = min(16, (b.y() - a.y()) / 2, abs(b.x() - a.x()) / 2)
                direction = 1 if b.x() > a.x() else -1
                path.lineTo(a.x(), middle_y - radius)
                path.quadTo(a.x(), middle_y, a.x() + direction * radius, middle_y)
                path.lineTo(b.x() - direction * radius, middle_y)
                path.quadTo(b.x(), middle_y, b.x(), middle_y + radius)
                path.lineTo(b)
                middle = QPointF((a.x() + b.x()) / 2, middle_y)
            else:
                path.lineTo(b)
                middle = (a + b) / 2
            self.scene().addPath(path, QPen(QColor("#5d5877"), 1.5))
            arrow = QPainterPath(b + (QPointF(-4, -6) if vertical or wrapping else QPointF(-6, -4)))
            arrow.lineTo(b)
            arrow.lineTo(b + (QPointF(4, -6) if vertical or wrapping else QPointF(-6, 4)))
            self.scene().addPath(arrow, QPen(QColor("#8d80ae"), 1.5))
            row = (
                visible[offset].start
                if offset < len(visible)
                else visible[-1].end
                if visible
                else 0
            )
            point = InsertPoint(self, row)
            point.setPos(middle)
            self.scene().addItem(point)
            if offset == len(visible):
                text = self.scene().addSimpleText(
                    "FINISH" if start + len(visible) == len(self.blocks) else "CONTINUED",
                    font(8, True),
                )
                text.setBrush(QColor(MUTED))
                text.setPos(b + QPointF(-20, 12))
        self.scene().setSceneRect(self.scene().itemsBoundingRect().adjusted(-30, -25, 45, 60))
        self.scene().blockSignals(False)

        if self.execution_trace is not None:
            self.set_execution_trace(self.execution_trace, reveal=False)

    def choose_indices(self, indices, emit=True, reveal=False):
        self.selected_indices = {i for i in indices if 0 <= i < len(self.blocks)}
        if reveal and self.selected_indices:
            index = min(self.selected_indices)
            if index // PAGE_SIZE != self.page:
                self.page = index // PAGE_SIZE
                self.render_page()
        self.scene().blockSignals(True)
        for i, node in self.nodes.items():
            node.setSelected(i in self.selected_indices)
        self.scene().blockSignals(False)
        if reveal and self.selected_indices and min(self.selected_indices) in self.nodes:
            self.ensureVisible(self.nodes[min(self.selected_indices)], 40, 40)
        if emit:
            self.selected.emit([self.blocks[i] for i in sorted(self.selected_indices)])

    def selection_changed(self):
        selected = {item.index for item in self.scene().selectedItems() if isinstance(item, Node)}
        outside = self.selected_indices - set(self.nodes)
        self.selected_indices = outside | selected
        self.selected.emit([self.blocks[i] for i in sorted(self.selected_indices)])

    def select_row(self, row, reveal=True):
        if row >= 0 and self.blocks:
            self.choose_indices(
                {max(0, bisect_right(self.starts, row) - 1)}, emit=False, reveal=reveal
            )

    def request_selection_visibility(self):
        """Reveal after layout settles, without moving cards during a pointer gesture."""
        self.reveal_requested = True
        if not self.reveal_queued:
            self.reveal_queued = True
            QTimer.singleShot(0, self, self.reveal_selection)

    def reveal_selection(self):
        self.reveal_queued = False
        if not self.reveal_requested or self.pointer_interaction or not self.isVisible():
            return
        self.reveal_requested = False
        indices = sorted(self.selected_indices.intersection(self.nodes))
        if not indices:
            return
        bounds = QRectF()
        for index in indices:
            bounds = bounds.united(self.nodes[index].sceneBoundingRect())
        mapped = self.mapFromScene(bounds).boundingRect()
        if (
            mapped.width() + 48 > self.viewport().width()
            or mapped.height() + 48 > self.viewport().height()
        ):
            target = self.anchor if self.anchor in indices else indices[0]
            bounds = self.nodes[target].sceneBoundingRect()
        self.ensureVisible(bounds, 24, 24)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.pan_origin is None:
            self.request_selection_visibility()

    def highlight(self, row):
        index = max(0, bisect_right(self.starts, row) - 1) if row >= 0 and self.blocks else -1
        if index >= 0 and index // PAGE_SIZE != self.page:
            self.page = index // PAGE_SIZE
            self.render_page()
        for i, node in self.nodes.items():
            if node.playing != (i == index):
                node.playing = i == index
                node.update()
        if index in self.nodes:
            self.ensureVisible(self.nodes[index], 40, 40)

    def set_execution(self, states):
        self.execution_trace = None
        self.execution_states = dict(states)
        active = [i for i, state in states.items() if state == "running"]
        last = [i for i, state in states.items() if state in ("last", "stopped", "failed")]
        target = min(active) if active else min(last) if last else None
        if target is not None and target // PAGE_SIZE != self.page:
            self.page = target // PAGE_SIZE
            self.render_page()
        for index, node in self.nodes.items():
            state = states.get(index, "")
            if state != node.execution_state:
                node.execution_state = state
                node.playing = state == "running"
                node.update()
        if target in self.nodes:
            self.ensureVisible(self.nodes[target], 24, 24)

    def set_execution_trace(self, trace, reveal=True):
        self.execution_trace = trace
        row = trace["active_row"]
        if trace["phase"] == "finished":
            row = trace["failed_row"] if trace["failed_row"] >= 0 else trace["last_activity_row"]
        elif trace["phase"] not in ("paused", "countdown", "positioning", "settling", "loop_gap"):
            if row < 0:
                previous = trace["last_sent_row"]
                candidate = (
                    max(0, bisect_right(self.starts, previous) - 1)
                    if previous >= 0 and self.blocks
                    else -1
                )
                if (
                    candidate >= 0
                    and self.blocks[candidate].kind in ("move", "scroll")
                    and block_state(self.blocks[candidate], trace) == "running"
                ):
                    row = previous
                elif trace.get("held_rows"):
                    row = max(trace["held_rows"])
        else:
            row = -1
        target = max(0, bisect_right(self.starts, row) - 1) if row >= 0 and self.blocks else None
        if reveal and target is not None and target // PAGE_SIZE != self.page:
            self.page = target // PAGE_SIZE
            self.render_page()
        for index, node in self.nodes.items():
            state = block_state(node.block, trace)
            if state != node.execution_state:
                node.execution_state = state
                node.playing = state == "running"
                node.update()
        if reveal and target in self.nodes:
            self.ensureVisible(self.nodes[target], 24, 24)

    def zoom(self, factor):
        current = self.transform().m11()
        target = max(0.4, min(1.8, current * factor))
        self.scale(target / current, target / current)
        self.zoomChanged.emit(round(target * 100))

    def fit(self):
        bounds = self.sceneRect()
        scale = max(
            0.5,
            min(
                1,
                (self.viewport().width() - 30) / max(1, bounds.width()),
                (self.viewport().height() - 30) / max(1, bounds.height()),
            ),
        )
        self.resetTransform()
        self.scale(scale, scale)
        self.centerOn(bounds.center())
        if (
            bounds.width() * scale > self.viewport().width()
            or bounds.height() * scale > self.viewport().height()
        ):
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().minimum())
            self.verticalScrollBar().setValue(self.verticalScrollBar().minimum())
        self.zoomChanged.emit(round(scale * 100))

    def mousePressEvent(self, event):
        if event.button() in (Qt.LeftButton, Qt.MiddleButton):
            self.pointer_interaction = True
        if event.button() == Qt.MiddleButton:
            self.reveal_requested = False
            self.pan_origin = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.LeftButton and not event.modifiers() & Qt.ControlModifier:
            if not isinstance(
                self.itemAt(event.position().toPoint()), (Node, InsertPoint, StartPoint)
            ):
                self.choose_indices(set())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.pan_origin is not None:
            delta = event.position().toPoint() - self.pan_origin
            self.pan_origin = event.position().toPoint()
            for bar, offset in (
                (self.horizontalScrollBar(), delta.x()),
                (self.verticalScrollBar(), delta.y()),
            ):
                bar.setValue(bar.value() - offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.pan_origin = None
            self.unsetCursor()
            self.pointer_interaction = False
            if self.reveal_requested:
                self.request_selection_visibility()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            self.pointer_interaction = False
            if self.reveal_requested:
                self.request_selection_visibility()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.zoom(1.12 if event.angleDelta().y() > 0 else 1 / 1.12)
        elif self.layout_mode == "horizontal" and not event.modifiers() & Qt.ShiftModifier:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - event.angleDelta().y())
        else:
            super().wheelEvent(event)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F1:
            self.command.emit("help")
            return
        command = editing_command(event)
        arrows = {Qt.Key_Left: "left", Qt.Key_Right: "right", Qt.Key_Up: "up", Qt.Key_Down: "down"}
        if event.key() in arrows:
            direction = arrows[event.key()]
            command = (
                direction
                if event.modifiers() & Qt.AltModifier
                else ("extend_" if event.modifiers() & Qt.ShiftModifier else "select_") + direction
            )
        if event.modifiers() & Qt.ControlModifier and event.key() in (
            Qt.Key_Plus,
            Qt.Key_Equal,
            Qt.Key_Minus,
            Qt.Key_0,
        ):
            self.fit() if event.key() == Qt.Key_0 else self.zoom(
                1 / 1.2 if event.key() == Qt.Key_Minus else 1.2
            )
        elif command:
            self.command.emit(command)
        else:
            super().keyPressEvent(event)


class Workflow(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = Canvas()
        self.run_summary = QLabel("")
        self.run_summary.setObjectName("muted")
        self.run_summary.setWordWrap(True)
        self.run_summary.setContentsMargins(12, 8, 12, 0)
        self.run_summary.hide()
        layout.addWidget(self.run_summary)
        self.selection_bar = QWidget()
        selection = QHBoxLayout(self.selection_bar)
        selection.setContentsMargins(10, 5, 10, 5)
        self.selection_label = QLabel("No actions selected")
        self.selection_label.setObjectName("muted")
        selection.addWidget(self.selection_label)
        for text, command in (
            ("Copy", "copy"),
            ("Paste", "paste"),
            ("Duplicate", "duplicate"),
            ("Re-record", "rerecord"),
            ("Delete", "delete"),
        ):
            btn = QPushButton(text)
            btn.setObjectName("ghost")
            btn.clicked.connect(lambda checked=False, c=command: self.canvas.command.emit(c))
            selection.addWidget(btn)
        selection.addStretch()
        layout.addWidget(self.selection_bar)
        layout.addWidget(self.canvas, 1)
        footer = QHBoxLayout()
        footer.setContentsMargins(14, 8, 14, 8)
        self.page_label = QLabel("Actions run from left to right")
        self.page_label.setObjectName("muted")
        self.page_label.setWordWrap(True)
        footer.addWidget(self.page_label)
        self.previous = QPushButton("Previous")
        self.next = QPushButton("Next")
        for widget, delta in ((self.previous, -1), (self.next, 1)):
            widget.setObjectName("ghost")
            widget.clicked.connect(lambda checked=False, d=delta: self.change_page(d))
            footer.addWidget(widget)
        footer.addStretch()
        keys = QPushButton("Keys · F1")
        keys.setObjectName("ghost")
        keys.clicked.connect(lambda: self.canvas.command.emit("help"))
        footer.addWidget(keys)
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
        self.layout_choice = QComboBox()
        for text, value in (
            ("Horizontal", "horizontal"),
            ("Vertical", "vertical"),
            ("Grid", "grid"),
        ):
            self.layout_choice.addItem(text, value)
        self.layout_choice.setToolTip("Layout only; playback always follows action numbers")
        self.layout_choice.currentIndexChanged.connect(self.apply_layout)
        footer.insertWidget(1, self.layout_choice)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("muted")
        footer.addWidget(self.zoom_label)
        self.canvas.zoomChanged.connect(lambda value: self.zoom_label.setText(f"{value}%"))
        layout.addLayout(footer)
        self.update_footer()

    def update_footer(self):
        count = len(self.canvas.blocks)
        selected = len(self.canvas.selected_indices)
        self.selection_label.setText(f"{selected:,} selected")
        self.selection_bar.setVisible(selected > 0)
        self.previous.setVisible(count > PAGE_SIZE)
        self.next.setVisible(count > PAGE_SIZE)
        self.previous.setEnabled(self.canvas.page > 0)
        self.next.setEnabled((self.canvas.page + 1) * PAGE_SIZE < count)
        self.page_label.setText(
            f"{count:,} actions · Drag to select"
            if count <= PAGE_SIZE
            else f"Actions {self.canvas.page * PAGE_SIZE + 1:,}–{min(count, (self.canvas.page + 1) * PAGE_SIZE):,} of {count:,}"
        )

    def apply_layout(self):
        self.canvas.layout_mode = self.layout_choice.currentData()
        self.canvas.render_page()
        self.canvas.fit()

    def change_page(self, delta):
        page = self.canvas.page + delta
        if 0 <= page <= (len(self.canvas.blocks) - 1) // PAGE_SIZE:
            self.canvas.page = page
            self.canvas.render_page()
            self.canvas.horizontalScrollBar().setValue(0)
            self.update_footer()
