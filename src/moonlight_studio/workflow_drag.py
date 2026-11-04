"""Drag previews simulate layout changes until one undoable drop commits them."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtWidgets import QGraphicsItem


class WorkflowDragMixin:
    def preview_drag(self, source, origin, position):
        from .workflow import CARD_HEIGHT, CARD_WIDTH, PITCH, Node, OriginMarker

        if self.drag_state is None:
            selected = set(self.selected_indices) if source in self.selected_indices else {source}
            origins = {i: node.pos() for i, node in self.nodes.items() if i in selected}
            self.drag_state = dict(
                source=source,
                selected=selected,
                origins=origins,
                origin=origin,
                target=None,
                mapping={},
                pointer=QPointF(),
            )
            for index, point in origins.items():
                marker = OriginMarker(self.blocks[index].title)
                marker.setPos(point)
                self.scene().addItem(marker)
                self.drag_items.append(marker)
            self.drag_scroll.start()
        state = self.drag_state
        state["pointer"] = self.mapFromScene(position)
        delta = position - origin
        destination = self.node_position(source) + delta
        if self.layout_mode == "vertical":
            target = round((destination.y() - 110) / 214)
        elif self.layout_mode == "grid":
            target = max(0, round((destination.y() - 136) / 224)) * 4 + max(
                0, min(3, round((destination.x() - 136) / PITCH))
            )
        else:
            target = round((destination.x() - 136) / PITCH)
        target = max(0, min(len(self.blocks) - 1, target))
        target = None if target in state["selected"] else target
        if target != state["target"]:
            state["target"] = target
            for item in self.drag_preview_items:
                self.remove_scene_item(item)
            self.drag_preview_items = []
            if target is None:
                state["mapping"] = {}
            else:
                selected = sorted(state["selected"])
                boundary = target + 1 if target > source else target
                remaining = [i for i in range(len(self.blocks)) if i not in state["selected"]]
                insertion = boundary - sum(i < boundary for i in selected)
                order = remaining[:insertion] + selected + remaining[insertion:]
                state["mapping"] = {index: slot for slot, index in enumerate(order)}
                visible = (
                    self.mapToScene(self.viewport().rect())
                    .boundingRect()
                    .adjusted(-PITCH, -224, PITCH, 224)
                )
                for index in selected:
                    slot = state["mapping"][index]
                    point = self.node_position(slot)
                    if visible.intersects(QRectF(point.x(), point.y(), CARD_WIDTH, CARD_HEIGHT)):
                        preview = Node(self.blocks[index], slot, self)
                        preview.setFlags(QGraphicsItem.GraphicsItemFlag(0))
                        preview.setAcceptedMouseButtons(Qt.NoButton)
                        preview.setAcceptHoverEvents(False)
                        preview.setOpacity(0.42)
                        preview.setPos(point)
                        preview.setZValue(1)
                        self.scene().addItem(preview)
                        self.drag_preview_items.append(preview)
        state["delta"] = delta
        self.apply_drag_positions()

    def apply_drag_positions(self):
        if self.drag_state is None:
            return
        state = self.drag_state
        for index, node in self.nodes.items():
            if index in state["origins"]:
                node.setPos(state["origins"][index] + state.get("delta", QPointF()))
                node.setOpacity(0.85)
                node.setZValue(3)
            elif index not in state["selected"]:
                node.preview_index = state["mapping"].get(index, index)
                node.setPos(self.node_position(node.preview_index))
                node.update()

    def scroll_drag(self):
        if self.drag_state is None:
            self.drag_scroll.stop()
            return
        state = self.drag_state
        pointer = state["pointer"]
        moved = False
        for bar, value, extent in (
            (self.horizontalScrollBar(), pointer.x(), self.viewport().width()),
            (self.verticalScrollBar(), pointer.y(), self.viewport().height()),
        ):
            delta = -18 if value < 35 else 18 if value > extent - 35 else 0
            if delta:
                before = bar.value()
                bar.setValue(before + delta)
                moved |= bar.value() != before
        if moved:
            self.update_visible_nodes()
            self.preview_drag(state["source"], state["origin"], self.mapToScene(pointer))

    def finish_drag(self, cancel=False):
        if self.drag_state is None:
            return None
        target = None if cancel else self.drag_state["target"]
        if cancel:
            source = self.nodes.get(self.drag_state["source"])
            if source is not None:
                source.collapse_on_click = False
        self.drag_scroll.stop()
        self.scene().blockSignals(True)
        try:
            for item in self.drag_items + self.drag_preview_items:
                self.remove_scene_item(item)
            self.drag_items, self.drag_preview_items = [], []
            self.drag_state = None
            for index, node in self.nodes.items():
                node.preview_index = index
                node.setPos(self.node_position(index))
                node.update()
                node.setOpacity(1)
                node.setZValue(0)
        finally:
            self.scene().blockSignals(False)
        self.queue_visible_nodes()
        return target
