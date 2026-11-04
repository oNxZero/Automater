"""Undoable visual notes and named groups, attached to the original events."""

from dataclasses import replace
from uuid import uuid4

from PySide6.QtWidgets import QDialog

from .dialogs import GroupDialog, NoteDialog
from .models import Step


class AnnotationsMixin:
    def compose_note(self, row=None):
        if self.busy:
            return
        dialog = NoteDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.insert_steps(
                [
                    Step(
                        0,
                        "note",
                        title=dialog.title.text().strip() or "Note",
                        text=dialog.text.toPlainText(),
                    )
                ],
                row,
                "Add note",
            )

    def group_selection(self, name=None, color="#b5a4fa"):
        rows = self.selected_rows()
        if self.busy or not rows:
            return
        identities = {self.model.steps[row].group_id for row in rows}
        identity = next(iter(identities)) if len(identities) == 1 else ""
        previous = self.model.groups.get(identity, {})
        if name is None:
            dialog = GroupDialog(self, previous.get("name", ""), previous.get("color", color))
            if dialog.exec() != QDialog.Accepted:
                return
            name, color = dialog.name.text().strip(), dialog.color.currentData()
        identity = identity or uuid4().hex
        groups = {**self.model.groups, identity: {"name": name, "color": color}}
        selected = set(rows)
        steps = [
            replace(step, group_id=identity) if i in selected else step
            for i, step in enumerate(self.model.steps)
        ]
        self.pending_rows = rows
        self.model.commit(steps, "Group actions", groups)

    def ungroup_selection(self):
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
        if action == "edit":
            self.group_selection()
        elif action == "ungroup":
            self.ungroup_selection()
