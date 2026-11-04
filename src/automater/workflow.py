"""Continuous workflow canvas with viewport virtualization and smooth playback follow."""

import html
import math
from bisect import bisect_right
from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QLinearGradient, QPainter, QPainterPath, QPen
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

from .camera import CameraFollower
from .connections import FlowConnection, connection_state
from .editor import editing_command
from .group_canvas import GroupCanvasMixin
from .run_feedback import block_state
from .theme import COLORS, MUTED, TEXT, font, icon, paint_color, shadow_color
from .workflow_drag import WorkflowDragMixin

VIRTUALIZE_AFTER = 160
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
    group_id: str = ""


def blocks_for(steps):
    result, i = [], 0
    while i < len(steps):
        step, end = steps[i], i + 1
        if step.action == "note":
            i += 1
            continue
        duration = step.delay_ms
        if (
            not step.standalone
            and step.action == "key_down"
            and end < len(steps)
            and not steps[end].standalone
            and steps[end].action == "key_up"
            and steps[end].code == step.code
            and steps[end].group_id == step.group_id
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
                and steps[end].group_id == step.group_id
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
                step.group_id,
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
        tooltip = f"{block.title}\nEvents {block.start + 1}–{block.end}\nClick to edit · drag to preview a new position"
        self.setToolTip("<qt>" + html.escape(tooltip).replace("\n", "<br>") + "</qt>")

    def boundingRect(self):
        return QRectF(-5, -5, CARD_WIDTH + 10, CARD_HEIGHT + 15)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        color = paint_color(
            {
                "completed": "#75d6c0",
                "last": "#83b8f2",
                "stopped": "#e8c58a",
                "failed": "#f2a3bc",
            }.get(self.execution_state, COLORS[self.block.kind])
        )
        rect = QRectF(0, 0, CARD_WIDTH, CARD_HEIGHT)
        painter.setPen(Qt.NoPen)
        painter.setBrush(shadow_color())
        painter.drawRoundedRect(rect.translated(0, 6), 12, 12)
        gradient = QLinearGradient(0, 0, CARD_WIDTH, CARD_HEIGHT)
        gradient.setColorAt(0, paint_color("#25283c" if self.isSelected() else "#222738"))
        gradient.setColorAt(1, paint_color("#1c2030"))
        border = (
            color
            if self.isSelected() or self.playing or self.execution_state
            else paint_color("#55566f" if self.hovered else "#353b50")
        )
        painter.setPen(QPen(border, 2 if self.isSelected() or self.playing else 1))
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, 12, 12)
        if self.emphasis:
            glow = paint_color(color)
            glow.setAlpha(round(22 * self.emphasis))
            painter.setBrush(glow)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 12, 12)
        if not self.block.enabled:
            painter.setOpacity(0.45)
        tint = paint_color(color)
        tint.setAlpha(30)
        painter.setBrush(tint)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(16, 16, 33, 33), 9, 9)
        name = "mouse" if self.block.kind == "mouse" else self.block.kind
        if self.block.title.startswith("Press "):
            name = "press"
        elif self.block.title.startswith("Release "):
            name = "release"
        painter.drawPixmap(22, 22, icon(name, color.name(), resolved=True).pixmap(21, 21))
        painter.setFont(font(8, True))
        painter.setPen(paint_color(MUTED))
        painter.drawText(
            QRectF(58, 17, 126, 28),
            Qt.AlignVCenter | Qt.AlignRight,
            f"{getattr(self, 'preview_index', self.index) + 1:02d}  ·  {self.execution_state.upper() if self.execution_state else 'SKIPPED' if not self.block.enabled else self.block.kind.upper()}",
        )
        painter.setFont(font(11, True))
        painter.setPen(paint_color(TEXT))
        painter.drawText(
            QRectF(16, 62, 174, 24),
            Qt.AlignVCenter,
            painter.fontMetrics().elidedText(self.block.title, Qt.ElideRight, 174),
        )
        painter.setFont(font(9))
        painter.setPen(paint_color("#a0aac5"))
        painter.drawText(QRectF(16, 88, 174, 20), Qt.AlignVCenter, self.block.detail)
        painter.setPen(QPen(paint_color("#32384c"), 1))
        painter.drawLine(16, 115, 188, 115)
        painter.setFont(font(8))
        painter.setPen(color)
        count = self.block.end - self.block.start
        painter.drawText(
            QRectF(16, 119, 70, 18),
            Qt.AlignVCenter,
            "Playing…" if self.playing else f"{count} event{'s' if count != 1 else ''}",
        )
        painter.setPen(paint_color("#929bb6"))
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
        self.animation.setEndValue(
            1.0 if self.hovered or self.isSelected() or self.playing else 0.0
        )
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
            self.canvas.preview_drag(self.index, self.origin, event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event):
        target = self.canvas.finish_drag()
        event.accept()
        if target is not None:
            self.canvas.reorderRequested.emit(self.index, target)
        elif self.collapse_on_click:
            self.canvas.choose_indices({self.index})

    def contextMenuEvent(self, event):
        if self.index not in self.canvas.selected_indices:
            self.canvas.choose_indices({self.index})
        menu = QMenu()
        for text, action in (
            ("Copy\tCtrl+C", "copy"),
            ("Notes for selected group…", "group_notes"),
            ("Group selection…\tCtrl+G", "group"),
            ("Ungroup selection\tCtrl+Shift+G", "ungroup"),
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


class OriginMarker(QGraphicsObject):
    def __init__(self, title):
        super().__init__()
        self.title = title
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setZValue(1.5)

    def boundingRect(self):
        return QRectF(-2, -26, CARD_WIDTH + 4, CARD_HEIGHT + 28)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(paint_color("#8f84b3"), 1.5, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(0, 0, CARD_WIDTH, CARD_HEIGHT), 12, 12)
        painter.setFont(font(8, True))
        painter.setPen(paint_color("#c4b3ef"))
        painter.drawText(QRectF(0, -26, CARD_WIDTH, 24), Qt.AlignCenter, "Original position")


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
        painter.setPen(QPen(paint_color("#49506b"), 1))
        painter.setBrush(paint_color("#202638"))
        painter.drawEllipse(QPointF(0, 0), 10, 10)
        painter.setPen(QPen(paint_color("#b1a5d4"), 1.4))
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
        painter.setBrush(paint_color("#28273d"))
        painter.setPen(QPen(paint_color("#8e7abb"), 1.5))
        painter.drawEllipse(QPointF(0, 0), 20, 20)
        painter.drawPixmap(-10, -10, icon("target", "#c5b7ed").pixmap(20, 20))
        painter.setPen(paint_color(MUTED))
        painter.setFont(font(8, True))
        painter.drawText(QRectF(-55, 26, 110, 20), Qt.AlignCenter, self.canvas.start_label)

    def mousePressEvent(self, event):
        self.canvas.command.emit("start_settings")
        event.accept()


class Canvas(GroupCanvasMixin, WorkflowDragMixin, QGraphicsView):
    selected = Signal(object)
    insertRequested = Signal(int)
    reorderRequested = Signal(int, int)
    command = Signal(str)
    zoomChanged = Signal(int)
    groupRequested = Signal(str, str)

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
        self._rendering = False
        self._render_queued = False
        self.decorations = {}
        self.start_marker = None
        self.drag_state = None
        self.drag_items = []
        self.drag_preview_items = []
        self.drag_scroll = QTimer(self)
        self.drag_scroll.setInterval(16)
        self.drag_scroll.timeout.connect(self.scroll_drag)
        self.follow_enabled = True
        self.follow_target = None
        self.follow_interrupted = False
        self.flow_timer = QTimer(self)
        self.flow_timer.setInterval(33)
        self.flow_timer.timeout.connect(self.animate_connections)
        self.camera = CameraFollower(self)
        self.camera.positionChanged.connect(self.centerOn)
        self.grid_columns = 4
        self._reflow_queued = False
        self._reflow_pending = False
        self.layout_mode = "horizontal"
        self.start_label = "START"
        self.execution_states = {}
        self.execution_trace = None
        self.groups = {}
        self.group_items = {}
        self.group_members, self.group_rects = {}, {}
        self.group_click_origin = self.group_click_id = None
        self.scene().selectionChanged.connect(self.selection_changed)
        self.horizontalScrollBar().valueChanged.connect(self.queue_visible_nodes)
        self.verticalScrollBar().valueChanged.connect(self.queue_visible_nodes)

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, paint_color("#131724"))
        painter.setPen(QPen(paint_color("#293044"), 1))
        spacing = 24
        left, top = (
            math.floor(rect.left() / spacing) * spacing,
            math.floor(rect.top() / spacing) * spacing,
        )
        for x in range(left, math.ceil(rect.right()), spacing):
            for y in range(top, math.ceil(rect.bottom()), spacing):
                painter.drawPoint(QPointF(x, y))

    def node_position(self, index):
        i = index
        if self.layout_mode == "vertical":
            return QPointF(136, 110 + i * 214)
        if self.layout_mode == "grid":
            return QPointF(
                136 + (i % self.grid_columns) * PITCH, 136 + (i // self.grid_columns) * 224
            )
        return QPointF(136 + i * PITCH, 136)

    def node_x(self, index):
        return self.node_position(index).x()

    def rebuild(self, blocks, selected_row=-1, groups=None, preserve_view=False):
        center = self.mapToScene(self.viewport().rect().center())
        self.blocks = blocks
        self.groups = groups or {}
        self.build_group_spans()
        self.starts = [b.start for b in blocks]
        self.selected_indices = set()
        if selected_row >= 0 and blocks:
            index = max(0, bisect_right(self.starts, selected_row) - 1)
            self.selected_indices = {index}
        self.render_canvas()
        if preserve_view:
            self.centerOn(center)
            self.update_visible_nodes()
        elif selected_row >= 0 and blocks:
            self.reveal_index(index)

    def render_canvas(self):
        if self.layout_mode == "grid":
            self.grid_columns = self.desired_grid_columns()
        self.camera.stop()
        self.follow_target = None
        self.drag_scroll.stop()
        self.drag_state = None
        self.drag_items, self.drag_preview_items = [], []
        self._rendering = True
        self.scene().blockSignals(True)
        self.scene().clear()
        self.nodes, self.decorations, self.group_items = {}, {}, {}
        self.update_scene_geometry()
        first = self.node_position(0)
        self.start_marker = StartPoint(self)
        self.start_marker.setPos(
            first
            + (
                QPointF(CARD_WIDTH / 2, -80)
                if self.layout_mode == "vertical"
                else QPointF(-76, CARD_HEIGHT / 2)
            )
        )
        self.scene().addItem(self.start_marker)
        self.scene().blockSignals(False)
        self._rendering = False
        self.update_visible_nodes()

    def update_scene_geometry(self):
        self.calculate_group_rects()
        last = self.node_position(max(0, len(self.blocks) - 1))
        right = (
            136 + (self.grid_columns - 1) * PITCH + CARD_WIDTH
            if self.layout_mode == "grid"
            else last.x() + CARD_WIDTH
        )
        self.scene().setSceneRect(
            QRectF(
                0,
                25,
                max(right + (35 if self.layout_mode == "grid" else 130), 380),
                last.y() + CARD_HEIGHT + 130,
            )
        )
        self.setSceneRect(self.scene().sceneRect())

    def visible_indices(self):
        count = len(self.blocks)
        if count <= VIRTUALIZE_AFTER:
            return set(range(count))
        rect = (
            self.mapToScene(self.viewport().rect())
            .boundingRect()
            .adjusted(-2 * PITCH, -448, 2 * PITCH, 448)
        )
        if self.layout_mode == "grid":
            first = max(0, math.floor((rect.top() - 136) / 224))
            last = min((count - 1) // self.grid_columns, math.ceil((rect.bottom() - 136) / 224))
            columns = range(
                max(0, math.floor((rect.left() - 136) / PITCH)),
                min(self.grid_columns - 1, math.ceil((rect.right() - 136) / PITCH)) + 1,
            )
            return {
                r * self.grid_columns + c
                for r in range(first, last + 1)
                for c in columns
                if r * self.grid_columns + c < count
            }
        start, end, pitch, origin = (
            (rect.top(), rect.bottom(), 214, 110)
            if self.layout_mode == "vertical"
            else (rect.left(), rect.right(), PITCH, 136)
        )
        return set(
            range(
                max(0, math.floor((start - origin) / pitch)),
                min(count - 1, math.ceil((end - origin) / pitch)) + 1,
            )
        )

    def queue_visible_nodes(self, *_):
        if not self._rendering and not self._render_queued:
            self._render_queued = True
            QTimer.singleShot(0, self, self.update_visible_nodes)

    def remove_scene_item(self, item):
        self.scene().removeItem(item)
        if isinstance(item, QGraphicsObject):
            item.deleteLater()

    def update_visible_nodes(self):
        self._render_queued = False
        if self._rendering:
            return
        wanted = self.visible_indices()
        if self.drag_state is not None:
            wanted.update(self.drag_state["origins"])
        self.scene().blockSignals(True)
        try:
            for index in set(self.nodes) - wanted:
                node = self.nodes.pop(index)
                node.animation.stop()
                self.remove_scene_item(node)
            for index in wanted - set(self.nodes):
                block = self.blocks[index]
                node = Node(block, index, self)
                node.setPos(self.node_position(index))
                node.setSelected(index in self.selected_indices)
                node.execution_state = (
                    block_state(block, self.execution_trace)
                    if self.execution_trace is not None
                    else self.execution_states.get(index, "")
                )
                node.playing = node.execution_state == "running"
                self.scene().addItem(node)
                self.nodes[index] = node
            boundaries = {boundary for i in wanted for boundary in (i, i + 1)}
            for boundary in set(self.decorations) - boundaries:
                for item in self.decorations.pop(boundary):
                    self.remove_scene_item(item)
            for boundary in boundaries - set(self.decorations):
                self.decorations[boundary] = self.make_connector(boundary)
            self.update_group_frames(wanted)
        finally:
            self.scene().blockSignals(False)
        self.apply_drag_positions()
        self.update_connections()

    def update_connections(self):
        animated = False
        for boundary, items in self.decorations.items():
            state = connection_state(boundary, self.blocks, self.starts, self.execution_trace)
            for item in items:
                if isinstance(item, FlowConnection):
                    item.set_state(state)
                    animated |= state == "running"
        if animated and self.isVisible():
            if not self.flow_timer.isActive():
                self.flow_timer.start()
        else:
            self.flow_timer.stop()

    def animate_connections(self):
        if not self.isVisible():
            self.flow_timer.stop()
            return
        for items in self.decorations.values():
            for item in items:
                if isinstance(item, FlowConnection) and item.state == "running":
                    item.update()

    def make_connector(self, boundary):
        items = []
        vertical = self.layout_mode == "vertical"
        start_pos = self.start_marker.pos()
        previous = self.node_position(boundary - 1) if boundary else None
        next_pos = self.node_position(boundary) if boundary < len(self.blocks) else None
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
            self.layout_mode == "grid"
            and boundary
            and boundary % self.grid_columns == 0
            and next_pos is not None
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
        arrow = QPainterPath(b + (QPointF(-4, -6) if vertical or wrapping else QPointF(-6, -4)))
        arrow.lineTo(b)
        arrow.lineTo(b + (QPointF(4, -6) if vertical or wrapping else QPointF(-6, 4)))
        connection = FlowConnection(path, arrow)
        self.scene().addItem(connection)
        items.append(connection)
        row = (
            self.blocks[boundary].start
            if boundary < len(self.blocks)
            else self.blocks[-1].end
            if self.blocks
            else 0
        )
        point = InsertPoint(self, row)
        point.setPos(middle)
        self.scene().addItem(point)
        items.append(point)
        if boundary == len(self.blocks):
            text = self.scene().addSimpleText(
                "FINISH",
                font(8, True),
            )
            text.setBrush(paint_color(MUTED))
            text.setPos(b + QPointF(-20, 12))
            items.append(text)
        return items

    def reveal_index(self, index):
        if 0 <= index < len(self.blocks):
            self.camera.stop()
            self.ensureVisible(QRectF(self.node_position(index), self.card_size()), 40, 40)
            self.update_visible_nodes()

    @staticmethod
    def card_size():
        from PySide6.QtCore import QSizeF

        return QSizeF(CARD_WIDTH, CARD_HEIGHT)

    def follow_index(self, index, force=False):
        previous = self.follow_target
        self.follow_target = index
        if (
            not self.isVisible()
            or not self.follow_enabled
            or self.pointer_interaction
            or (index == previous and not force)
        ):
            return
        if not 0 <= index < len(self.blocks):
            return
        self.follow_interrupted = False
        current = self.mapToScene(self.viewport().rect().center())
        destination = self.node_position(index) + QPointF(CARD_WIDTH / 2, CARD_HEIGHT / 2)
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        bounds = self.sceneRect()
        for axis, span, low, high in (
            ("x", visible.width(), bounds.left(), bounds.right()),
            ("y", visible.height(), bounds.top(), bounds.bottom()),
        ):
            value = getattr(destination, axis)()
            clamped = (
                (low + high) / 2
                if high - low <= span
                else max(low + span / 2, min(high - span / 2, value))
            )
            getattr(destination, "set" + axis.upper())(clamped)
        self.camera.move_to(current, destination)

    def set_follow_enabled(self, enabled):
        self.follow_enabled = enabled
        self.camera.stop()
        target = self.follow_target
        self.follow_target = None
        if enabled and target is not None:
            self.follow_index(target)

    def choose_indices(self, indices, emit=True, reveal=False):
        self.selected_indices = {i for i in indices if 0 <= i < len(self.blocks)}
        self.scene().blockSignals(True)
        for i, node in self.nodes.items():
            node.setSelected(i in self.selected_indices)
        self.scene().blockSignals(False)
        if reveal and self.selected_indices:
            self.reveal_index(min(self.selected_indices))
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
        if self.camera.timer.isActive() and not self.follow_interrupted:
            return
        indices = sorted(self.selected_indices.intersection(self.nodes))
        if not indices:
            return
        bounds = QRectF()
        for index in indices:
            bounds = bounds.united(self.nodes[index].sceneBoundingRect())
        grouped = any(self.blocks[index].group_id for index in indices)
        if grouped:
            bounds = bounds.adjusted(-14, -32, 14, 14)
        mapped = self.mapFromScene(bounds).boundingRect()
        if (
            mapped.width() + 48 > self.viewport().width()
            or mapped.height() + 48 > self.viewport().height()
        ):
            target = self.anchor if self.anchor in indices else indices[0]
            bounds = self.nodes[target].sceneBoundingRect()
            if self.blocks[target].group_id:
                bounds = bounds.adjusted(-14, -32, 14, 14)
        self.ensureVisible(bounds, 24, 24)

    def desired_grid_columns(self):
        width = self.viewport().width() / max(0.1, self.transform().m11())
        return max(1, min(64, math.floor((width - 136 - 35 - CARD_WIDTH) / PITCH) + 1))

    def queue_reflow(self):
        self._reflow_pending = True
        if not self._reflow_queued:
            self._reflow_queued = True
            QTimer.singleShot(0, self, self.reflow_grid)

    def reflow_grid(self):
        self._reflow_queued = False
        if self.layout_mode != "grid":
            self._reflow_pending = False
            return
        if self.pointer_interaction or self.drag_state is not None:
            return
        self._reflow_pending = False
        if self.desired_grid_columns() == self.grid_columns:
            return
        playback_target = (
            self.follow_target
            if self.execution_trace and self.follow_enabled and not self.follow_interrupted
            else None
        )
        if self.selected_indices:
            anchor = (
                self.anchor if self.anchor in self.selected_indices else min(self.selected_indices)
            )
        elif self.verticalScrollBar().value() <= self.verticalScrollBar().minimum() + 1:
            anchor = 0
        else:
            center = self.mapToScene(self.viewport().rect().center())
            row = max(0, round((center.y() - 136 - CARD_HEIGHT / 2) / 224))
            column = max(
                0, min(self.grid_columns - 1, round((center.x() - 136 - CARD_WIDTH / 2) / PITCH))
            )
            anchor = min(max(0, len(self.blocks) - 1), row * self.grid_columns + column)
        self.camera.stop()
        self.follow_target = None
        self.grid_columns = self.desired_grid_columns()
        self.update_scene_geometry()
        for index, node in self.nodes.items():
            node.setPos(self.node_position(index))
        for items in self.decorations.values():
            for item in items:
                self.remove_scene_item(item)
        self.decorations = {}
        for item in self.group_items.values():
            self.remove_scene_item(item)
        self.group_items = {}
        if playback_target is not None:
            self.update_visible_nodes()
            self.follow_index(playback_target, force=True)
        elif not self.execution_trace or self.execution_trace["phase"] == "finished":
            self.reveal_index(anchor)
        else:
            self.update_visible_nodes()

    def hideEvent(self, event):
        self.camera.stop()
        self.flow_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self.follow_target is not None and not self.follow_interrupted:
            self.follow_index(self.follow_target, force=True)
        self.update_connections()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.queue_reflow()
        self.queue_visible_nodes()
        if (
            self.execution_trace
            and self.follow_enabled
            and self.follow_target is not None
            and not self.follow_interrupted
        ):
            # Resizing the finished-run banner must not reveal an old selection
            # while the playback camera is moving toward the bottom of the scene.
            QTimer.singleShot(
                0,
                self,
                lambda: (
                    self.follow_index(self.follow_target, force=True)
                    if self.follow_target is not None
                    else None
                ),
            )
        elif self.pan_origin is None:
            self.request_selection_visibility()

    def highlight(self, row):
        index = max(0, bisect_right(self.starts, row) - 1) if row >= 0 and self.blocks else -1
        if index >= 0:
            self.follow_index(index)
        for i, node in self.nodes.items():
            if node.playing != (i == index):
                node.playing = i == index
                node.update()

    def set_execution(self, states):
        self.execution_trace = None
        self.execution_states = dict(states)
        active = [i for i, state in states.items() if state == "running"]
        last = [i for i, state in states.items() if state in ("last", "stopped", "failed")]
        target = min(active) if active else min(last) if last else None
        if not states:
            self.camera.stop()
            self.follow_target = None
            self.follow_interrupted = False
        if target is not None:
            self.follow_index(target)
        for index, node in self.nodes.items():
            state = states.get(index, "")
            if state != node.execution_state:
                node.execution_state = state
                node.playing = state == "running"
                node.update()
        self.update_connections()

    def set_execution_trace(self, trace, reveal=True):
        self.execution_trace = trace
        # Camera progress follows dispatch order, independently of held-key highlights.
        # Following an older held press after a release used to scroll backwards.
        row = max(trace.get("last_sent_row", -1), trace["active_row"])
        if trace["phase"] == "finished":
            row = max(trace["failed_row"], trace["last_activity_row"])
        elif trace["phase"] in (
            "paused",
            "preparing",
            "countdown",
            "activating",
            "positioning",
            "settling",
            "loop_gap",
        ):
            row = -1
        target = max(0, bisect_right(self.starts, row) - 1) if row >= 0 and self.blocks else None
        if reveal and target is not None:
            self.follow_index(target)
        for index, node in self.nodes.items():
            state = block_state(node.block, trace)
            if state != node.execution_state:
                node.execution_state = state
                node.playing = state == "running"
                node.update()
        self.update_connections()

    def zoom(self, factor):
        current = self.transform().m11()
        target = max(0.4, min(1.8, current * factor))
        self.camera.stop()
        self.scale(target / current, target / current)
        self.queue_reflow()
        self.update_visible_nodes()
        self.zoomChanged.emit(round(target * 100))

    def fit(self):
        self.camera.stop()
        if self.layout_mode == "grid":
            self.resetTransform()
            self.reflow_grid()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().minimum())
            self.verticalScrollBar().setValue(self.verticalScrollBar().minimum())
            self.update_visible_nodes()
            self.zoomChanged.emit(100)
            return
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
        self.update_visible_nodes()
        self.zoomChanged.emit(round(scale * 100))

    def mousePressEvent(self, event):
        self.group_click_id = None
        if event.button() == Qt.LeftButton:
            position = event.position().toPoint()
            item = self.itemAt(position)
            if not isinstance(item, (Node, InsertPoint, StartPoint)):
                self.group_click_id = self.group_at(self.mapToScene(position))
                self.group_click_origin = position
        if event.button() in (Qt.LeftButton, Qt.MiddleButton):
            self.follow_interrupted = True
            self.camera.stop()
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
            if self._reflow_pending:
                self.queue_reflow()
            if self.reveal_requested:
                self.request_selection_visibility()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            self.pointer_interaction = False
            identity, self.group_click_id = self.group_click_id, None
            if (
                identity is not None
                and self.group_click_origin is not None
                and (event.position().toPoint() - self.group_click_origin).manhattanLength() < 6
            ):
                point = self.mapToScene(event.position().toPoint())
                candidates = [
                    index for index in self.nodes if self.blocks[index].group_id == identity
                ]
                if candidates:
                    self.anchor = min(
                        candidates,
                        key=lambda index: (
                            self.nodes[index].sceneBoundingRect().center() - point
                        ).manhattanLength(),
                    )
                self.groupRequested.emit(identity, "inspect")
            if self._reflow_pending:
                self.queue_reflow()
            if self.reveal_requested:
                self.request_selection_visibility()

    def wheelEvent(self, event):
        self.follow_interrupted = True
        self.camera.stop()
        if event.modifiers() & Qt.ControlModifier:
            self.zoom(1.12 if event.angleDelta().y() > 0 else 1 / 1.12)
        elif self.layout_mode == "horizontal" and not event.modifiers() & Qt.ShiftModifier:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - event.angleDelta().y())
        else:
            super().wheelEvent(event)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.drag_state is not None:
            self.finish_drag(cancel=True)
            event.accept()
            return
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
            ("Group", "group"),
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
        self.action_count = QLabel("Actions run from left to right")
        self.action_count.setObjectName("muted")
        self.action_count.setWordWrap(True)
        footer.addWidget(self.action_count)
        self.follow_btn = QPushButton("Follow playback")
        self.follow_btn.setObjectName("segment")
        self.follow_btn.setCheckable(True)
        self.follow_btn.setChecked(True)
        self.follow_btn.setToolTip("Smoothly follow the running action")
        self.follow_btn.toggled.connect(self.canvas.set_follow_enabled)
        footer.addWidget(self.follow_btn)
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
        self.action_count.setText(f"{count:,} actions")

    def apply_layout(self):
        self.canvas.layout_mode = self.layout_choice.currentData()
        self.canvas.render_canvas()
        self.canvas.fit()
