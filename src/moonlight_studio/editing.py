"""Workflow selection and undoable editing shared with the precise event table."""

from bisect import bisect_right
from dataclasses import replace

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QMimeData
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMenu, QMessageBox

from .action_dialog import ActionDialog
from .actions import (
    CLIPBOARD_MIME,
    KINDS,
    MAX_CLIPBOARD_BYTES,
    create_action,
    decode_steps,
    encode_steps,
    randomize_steps,
)
from .models import MAX_STEPS
from .theme import icon
from .workflow import PAGE_SIZE, blocks_for


class EditingMixin:
    def refresh_workflow(self):
        self.blocks = blocks_for(self.model.steps)
        row = min(self.selection_anchor, len(self.model.steps) - 1)
        self.workflow.canvas.rebuild(self.blocks, row)
        if self.pending_rows is not None:
            rows, self.pending_rows = self.pending_rows, None
            indices = {
                max(0, bisect_right(self.workflow.canvas.starts, r) - 1)
                for r in rows
                if 0 <= r < len(self.model.steps)
            }
        else:
            rows = getattr(self, "_event_selection_rows", [row])
            indices = set(self.workflow.canvas.selected_indices)
        events = self.events_btn.isChecked()
        if events:
            rows = [r for r in rows if 0 <= r < len(self.model.steps)]
            indices = {max(0, bisect_right(self.workflow.canvas.starts, r) - 1) for r in rows}
            self.set_table_rows(rows)
        self.select_blocks(
            [self.blocks[i] for i in sorted(indices)], open_inspector=False, preserve_table=events
        )
        self.update_stats()
        if self.pages.currentIndex() == 0:
            self.navigate(0, 1 if self.events_btn.isChecked() else 0)

    def select_block(self, block, open_inspector=True):
        self.select_blocks([] if block is None else [block], open_inspector)

    def set_table_rows(self, rows):
        rows = sorted(set(rows))
        self._event_selection_rows = rows
        self._sync_selection = True
        try:
            selection = QItemSelection()
            first = previous = None
            for row in rows + [None]:
                if first is not None and (row is None or row != previous + 1):
                    selection.select(
                        self.model.index(first, 0),
                        self.model.index(previous, self.model.columnCount() - 1),
                    )
                    first = None
                if row is not None:
                    if first is None:
                        first = row
                    previous = row
            self.table.clearSelection()
            self.table.selectionModel().select(
                selection, QItemSelectionModel.Select | QItemSelectionModel.Rows
            )
        finally:
            self._sync_selection = False

    def select_blocks(self, blocks, open_inspector=True, preserve_table=False):
        if self._sync_selection or (self.busy and open_inspector):
            return
        if not isinstance(blocks, list):
            blocks = [blocks] if blocks else []
        self._sync_selection = True
        try:
            self.active_block = blocks[0] if len(blocks) == 1 else None
            self.selection_anchor = blocks[0].start if blocks else -1
            indices = {
                max(0, bisect_right(self.workflow.canvas.starts, b.start) - 1) for b in blocks
            }
            self.workflow.canvas.choose_indices(indices, emit=False)
            if not preserve_table:
                self._event_selection_rows = [
                    row for block in blocks for row in range(block.start, block.end)
                ]
                self.table.clearSelection()
                ranges = []
                for block in blocks:
                    if ranges and ranges[-1][1] == block.start:
                        ranges[-1] = (ranges[-1][0], block.end)
                    else:
                        ranges.append((block.start, block.end))
                selection = QItemSelection()
                for first, end in ranges:
                    selection.select(
                        self.model.index(first, 0),
                        self.model.index(end - 1, self.model.columnCount() - 1),
                    )
                self.table.selectionModel().select(
                    selection, QItemSelectionModel.Select | QItemSelectionModel.Rows
                )
            if len(blocks) > 1:
                self.action_inspector.select_many(blocks, self.model.steps)
            else:
                self.action_inspector.select(self.active_block, self.model.steps)
            self.workflow.update_footer()
            if open_inspector and len(blocks) == 1:
                self.show_inspector(0)
        finally:
            self._sync_selection = False

    def table_selection_changed(self, *args):
        if self._sync_selection or self.busy:
            return
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        if not rows or not self.blocks:
            return
        self._event_selection_rows = rows
        indices = {max(0, bisect_right(self.workflow.canvas.starts, r) - 1) for r in rows}
        self.select_blocks(
            [self.blocks[i] for i in sorted(indices)], open_inspector=False, preserve_table=True
        )

    def selected_rows(self):
        if self.events_btn.isChecked():
            return sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [
            row
            for i in sorted(self.workflow.canvas.selected_indices)
            for row in range(self.blocks[i].start, self.blocks[i].end)
        ]

    def choose_action(self, row=None):
        if self.busy:
            return
        row = row if type(row) is int else None
        menu = QMenu(self)
        for kind, (title, glyph) in enumerate(KINDS):
            item = menu.addAction(icon(glyph), title)
            item.triggered.connect(lambda checked=False, k=kind, r=row: self.compose_action(k, r))
        menu.exec(QCursor.pos())

    def compose_action(self, kind, row=None):
        dialog = ActionDialog(kind, self)
        if dialog.exec() == QDialog.Accepted:
            self.insert_steps(dialog.steps, row, "Add action")

    def insert_steps(self, steps, row=None, description="Paste actions"):
        if self.busy or not steps:
            return
        if len(self.model.steps) + len(steps) > MAX_STEPS:
            self.show_error("The combined workflow exceeds 200,000 events")
            return
        selected = self.selected_rows()
        at = row if row is not None else selected[-1] + 1 if selected else len(self.model.steps)
        if not 0 <= at <= len(self.model.steps):
            raise ValueError("Invalid insertion position")
        self.selection_anchor = at
        self.pending_rows = list(range(at, at + len(steps)))
        self.model.commit(self.model.steps[:at] + list(steps) + self.model.steps[at:], description)
        self.navigate(0, 1 if self.events_btn.isChecked() else 0)
        if self.active_block and not self.events_btn.isChecked():
            self.select_block(self.active_block)
        self.workflow.canvas.select_row(at) if len(
            self.workflow.canvas.selected_indices
        ) == 1 else None

    def add_step(self, kind=0, row=None):
        self.insert_steps(
            create_action(
                kind,
                delay=100 if kind in (0, 1) else 16 if kind == 3 else 100,
                duration=250 if kind == 2 else 60,
            ),
            row,
            "Add action",
        )

    def apply_block(self, block, values):
        if self.busy or block not in self.blocks:
            return
        try:
            subset = list(self.model.steps[block.start : block.end])
            original = sum(s.delay_ms for s in subset[1:])
            original_max = sum(s.maximum_ms for s in subset[1:])
            new_max = values.get("duration_max")
            adjust = (
                values["duration"] != original
                or (new_max if new_max is not None else values["duration"]) != original_max
            )
            for i, step in enumerate(subset):
                edits = {"enabled": values["enabled"]}
                if i == 0:
                    edits.update(delay_ms=values["delay"], delay_max_ms=values.get("delay_max"))
                elif adjust:
                    weight = step.delay_ms / original if original else 1 / (len(subset) - 1)
                    edits.update(
                        delay_ms=values["duration"] * weight,
                        delay_max_ms=new_max * weight if new_max is not None else None,
                    )
                if block.kind in ("key", "mouse"):
                    edits["code"] = values["code"]
                elif block.kind in ("move", "scroll") and len(subset) == 1:
                    edits.update(x=values["x"], y=values["y"])
                subset[i] = replace(step, **edits)
            self.pending_rows = list(range(block.start, block.end))
            self.model.commit(
                self.model.steps[: block.start] + subset + self.model.steps[block.end :],
                "Edit action",
            )
            self.status.setText("Action updated · Ctrl+Z to undo")
        except (ValueError, TypeError) as exc:
            self.show_error(str(exc))

    def copy_selection(self):
        rows = self.selected_rows()
        if not rows:
            return False
        data = encode_steps([self.model.steps[r] for r in rows])
        mime = QMimeData()
        mime.setData(CLIPBOARD_MIME, data)
        mime.setText(data.decode())
        QApplication.clipboard().setMimeData(mime)
        self.status.setText(f"Copied {len(rows):,} events · Ctrl+V to paste")
        return True

    def paste_selection(self):
        mime = QApplication.clipboard().mimeData()
        if mime is None:
            return
        raw = (
            mime.data(CLIPBOARD_MIME) if mime.hasFormat(CLIPBOARD_MIME) else mime.data("text/plain")
        )
        if raw.size() > MAX_CLIPBOARD_BYTES:
            raise ValueError("Clipboard exceeds the 32 MiB limit")
        self.insert_steps(decode_steps(bytes(raw)))

    def duplicate(self):
        if not self.busy:
            self.insert_steps(
                [self.model.steps[r] for r in self.selected_rows()], description="Duplicate actions"
            )

    def delete(self):
        if self.busy:
            return
        rows = set(self.selected_rows())
        if not rows:
            return
        steps = [s for i, s in enumerate(self.model.steps) if i not in rows]
        self.pending_rows = [min(min(rows), len(steps) - 1)] if steps else []
        self.model.commit(steps, "Delete selection")

    def reorder_blocks(self, source, target):
        if (
            self.busy
            or source == target
            or not 0 <= source < len(self.blocks)
            or not 0 <= target < len(self.blocks)
        ):
            return
        selected = self.workflow.canvas.selected_indices
        selected = selected if source in selected else {source}
        if target in selected:
            return
        rows = {r for i in selected for r in range(self.blocks[i].start, self.blocks[i].end)}
        boundary = self.blocks[target].end if target > source else self.blocks[target].start
        destination = sum(i not in rows for i in range(boundary))
        moving = [s for i, s in enumerate(self.model.steps) if i in rows]
        remaining = [s for i, s in enumerate(self.model.steps) if i not in rows]
        self.pending_rows = list(range(destination, destination + len(moving)))
        self.selection_anchor = destination
        self.model.commit(
            remaining[:destination] + moving + remaining[destination:], "Move actions"
        )

    def move(self, direction):
        if self.busy:
            return
        rows = self.selected_rows()
        if not rows or rows[0] + direction < 0 or rows[-1] + direction >= len(self.model.steps):
            return
        steps = list(self.model.steps)
        for row in rows if direction < 0 else reversed(rows):
            steps[row], steps[row + direction] = steps[row + direction], steps[row]
        self.pending_rows = [r + direction for r in rows]
        self.model.commit(steps, "Move events")

    def workflow_command(self, command):
        if self.busy:
            return
        if command == "start_settings":
            self.show_inspector(2)
            return
        if command == "help":
            QMessageBox.information(
                self,
                "Workflow shortcuts",
                "Ctrl+C / X / V  Copy / cut / paste\nCtrl+D  Duplicate\nCtrl+A  Select all actions (all pages)\nDelete / Backspace  Remove selection\nCtrl+Z / Ctrl+Shift+Z  Undo / redo\nEsc  Clear selection\n\nCtrl-click  Add/remove an action\nShift-click or Shift+arrows  Select a range\nShift-drag empty space  Box select\nAlt+arrows  Move selection\nDrag empty space  Pan\nCtrl+wheel or Ctrl+ +/−  Zoom\nCtrl+0  Fit\n\nF6  Record / finish\nF7  Run / stop\nF8  Pause / resume\nF12  Emergency stop",
            )
            return
        try:
            if command == "select_all":
                self.table.selectAll() if self.events_btn.isChecked() else self.workflow.canvas.choose_indices(
                    set(range(len(self.blocks)))
                )
            elif command == "clear_selection":
                self.select_blocks([])
            elif command in ("undo", "redo"):
                getattr(self.undo, command)()
            elif command == "copy":
                self.copy_selection()
            elif command == "cut":
                if self.copy_selection():
                    self.delete()
            elif command == "paste":
                self.paste_selection()
            elif command == "duplicate":
                self.duplicate()
            elif command == "delete":
                self.delete()
            elif command in ("toggle", "split", "fixed_timing", "randomize"):
                rows = self.selected_rows()
                if not rows:
                    return
                steps = list(self.model.steps)
                if command == "randomize":
                    percent, ok = QInputDialog.getDouble(
                        self,
                        "Randomize selected timing",
                        "Variation around current delays (±%)",
                        10,
                        0,
                        100,
                        1,
                    )
                    if not ok:
                        return
                    steps = randomize_steps(steps, rows, percent)
                else:
                    enabled = not all(steps[r].enabled for r in rows)
                    for row in rows:
                        changes = (
                            {"enabled": enabled}
                            if command == "toggle"
                            else {"standalone": True}
                            if command == "split"
                            else {"delay_max_ms": None}
                        )
                        steps[row] = replace(steps[row], **changes)
                self.pending_rows = rows
                self.model.commit(
                    steps,
                    {
                        "toggle": "Toggle selection",
                        "split": "Split actions",
                        "fixed_timing": "Use fixed timing",
                        "randomize": "Randomize timing",
                    }[command],
                )
            elif command in ("left", "right", "up", "down"):
                if self.events_btn.isChecked():
                    self.move(-1 if command in ("left", "up") else 1)
                elif self.workflow.canvas.selected_indices:
                    selected = self.workflow.canvas.selected_indices
                    before = command in ("left", "up")
                    self.reorder_blocks(
                        min(selected) if before else max(selected),
                        min(selected) - 1 if before else max(selected) + 1,
                    )
            elif command.startswith(("select_", "extend_")) and self.blocks:
                canvas = self.workflow.canvas
                selected = canvas.selected_indices
                backwards = command.endswith(("left", "up"))
                delta = -1 if backwards else 1
                if canvas.layout_mode == "grid" and command.endswith(("up", "down")):
                    delta *= 4
                current = (
                    (min(selected) if backwards else max(selected))
                    if selected
                    else (0 if backwards else -1)
                )
                target = max(0, min(len(self.blocks) - 1, current + delta))
                if command.startswith("extend_"):
                    anchor = canvas.anchor if canvas.anchor is not None else current
                    indices = set(range(min(anchor, target), max(anchor, target) + 1))
                else:
                    canvas.anchor = target
                    indices = {target}
                canvas.choose_indices(indices)
                if target // PAGE_SIZE != canvas.page:
                    canvas.page = target // PAGE_SIZE
                    canvas.render_page()
                if target in canvas.nodes:
                    canvas.ensureVisible(canvas.nodes[target], 40, 40)
                self.workflow.update_footer()
        except (ValueError, TypeError) as exc:
            self.show_error(str(exc))
