"""Undoable visual notes and named groups, attached to the original events."""

from dataclasses import replace
from uuid import uuid4

from PySide6.QtWidgets import QDialog

from .dialogs import GroupDialog


class AnnotationsMixin:
    def edit_selection_notes(self):
        if self.busy:
            return
        if not self.selected_rows():
            self.show_inspector(3)
            return
        identities = {self.model.steps[row].group_id for row in self.selected_rows()}
        identity = next(iter(identities)) if len(identities) == 1 else ""
        if identity:
            self.inspect_group(identity)
        else:
            self.group_selection()

    def inspect_group(self, identity):
        if self.busy or identity not in self.model.groups:
            return
        if not self.group_inspector.flush():
            self.show_error("Finish the current group name/notes before switching groups")
            return
        self.select_group(identity)
        self.group_inspector.select(identity, self.model.groups[identity])
        self.show_inspector(3)

    def save_group_notes(self, identity, name, color, notes):
        if self.busy or identity not in self.model.groups:
            return
        groups = {**self.model.groups, identity: {"name": name, "color": color, "notes": notes}}
        self.model.commit(self.model.steps, "Edit group notes", groups)

    def group_selection(self, name=None, color="#b5a4fa", notes=None):
        if not self.group_inspector.flush():
            return
        rows = self.selected_rows()
        if self.busy or not rows:
            return
        identities = {self.model.steps[row].group_id for row in rows}
        identity = next(iter(identities)) if len(identities) == 1 else ""
        previous = self.model.groups.get(identity, {})
        if identity and set(rows) != {
            i for i, step in enumerate(self.model.steps) if step.group_id == identity
        }:
            identity = (
                ""  # Grouping a subset creates a new category; it cannot rename other members.
            )
        if name is None:
            dialog = GroupDialog(
                self,
                previous.get("name", ""),
                previous.get("color", color),
                previous.get("notes", ""),
            )
            if dialog.exec() != QDialog.Accepted:
                return
            name, color, notes = (
                dialog.name.text().strip(),
                dialog.color.currentData(),
                dialog.notes.toPlainText(),
            )
        identity = identity or uuid4().hex
        groups = {
            **self.model.groups,
            identity: {
                "name": name,
                "color": color,
                "notes": previous.get("notes", "") if notes is None else notes,
            },
        }
        selected = set(rows)
        steps = [
            replace(step, group_id=identity) if i in selected else step
            for i, step in enumerate(self.model.steps)
        ]
        self.pending_rows = rows
        self.model.commit(steps, "Group actions", groups)
        if identity in self.model.groups:
            self.group_inspector.select(identity, self.model.groups[identity])
            self.show_inspector(3)

    def ungroup_selection(self):
        if not self.group_inspector.flush():
            return
        if self.busy:
            return
        rows = set(self.selected_rows())
        self.pending_rows = sorted(rows)
        self.model.commit(
            [
                replace(step, group_id="") if i in rows else step
                for i, step in enumerate(self.model.steps)
            ],
            "Ungroup actions",
        )

    def select_group(self, identity):
        indices = {i for i, block in enumerate(self.blocks) if block.group_id == identity}
        self.workflow.canvas.choose_indices(indices)

    def handle_group_command(self, identity, action):
        if self.busy:
            return
        self.select_group(identity)
        if action in ("edit", "inspect"):
            self.inspect_group(identity)
        elif action == "ungroup":
            self.ungroup_selection()
