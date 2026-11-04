"""Independent workflow documents, undo histories and recovery files."""

from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QTimer
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QMenu, QMessageBox

from . import storage
from .dialogs import NameDialog
from .models import Script


@dataclass
class WorkflowDocument:
    script: Script
    undo: QUndoStack
    saved: dict
    recovery: Path
    path: Path | None = None
    view: dict = field(default_factory=dict)
    last_run: dict | None = None


class DocumentsMixin:
    def document_id(self, index=None):
        index = self.document_tabs.currentIndex() if index is None else index
        return self.document_tabs.tabData(index) if index >= 0 else None

    def stash_document(self):
        doc = self.documents.get(self.active_document_id)
        if doc is None:
            return True
        try:
            script = self.script()
        except ValueError as exc:
            self.show_error(str(exc))
            return False
        doc.script, doc.path, doc.saved = script, self.path, self.saved_snapshot
        doc.last_run = self.last_run
        canvas = self.workflow.canvas
        doc.view = {
            "selection": self.selected_rows(),
            "layout": self.workflow.layout_choice.currentIndex(),
            "follow": self.workflow.follow_btn.isChecked(),
            "transform": canvas.transform(),
            "horizontal": canvas.horizontalScrollBar().value(),
            "vertical": canvas.verticalScrollBar().value(),
            "events": self.events_btn.isChecked(),
            "inspector": not self.inspector_panel.isHidden(),
            "inspector_tab": self.inspector_stack.currentIndex(),
            "group": self.group_inspector.identity,
            "speed": self.speed.value(),
            "repeats": self.repeats.value(),
            "countdown": self.countdown.value(),
            "gap": self.gap.value(),
            "test": self.test_mode.isChecked(),
            "mode": self.mode.currentIndex(),
            "activate_target": self.activate_target.isChecked(),
            "target": self.target.currentData(),
        }
        if doc.script.to_dict() != doc.saved:
            try:
                storage.save(doc.script, doc.recovery)
            except (OSError, ValueError) as exc:
                self.show_error(f"Autosave unavailable: {exc}")
        return True

    def update_document_title(self, dirty=None):
        if self.active_document_id is None:
            return
        for index in range(self.document_tabs.count()):
            if self.document_id(index) == self.active_document_id:
                title = (
                    self.path.stem if self.path else self.name.text().strip() or "Untitled workflow"
                ).replace("&", "&&")
                self.document_tabs.setTabText(
                    index, title + (" *" if (self.dirty() if dirty is None else dirty) else "")
                )
                self.document_tabs.setTabToolTip(
                    index, str(self.path) if self.path else "Unsaved workflow"
                )
                break

    def document_menu(self, position):
        index = self.document_tabs.tabAt(position)
        if self.busy or index < 0:
            return
        menu = QMenu(self)
        for title, callback in (
            ("Rename…", lambda: self.rename_document(index)),
            ("Save", lambda: self.document_action(index, self.save_script)),
            ("Save as…", lambda: self.document_action(index, self.save_as)),
            ("Close workflow", lambda: self.close_document(index)),
            ("Close other workflows", lambda: self.close_other_documents(index)),
        ):
            menu.addAction(title, callback)
        menu.exec(self.document_tabs.mapToGlobal(position))

    def document_action(self, index, callback):
        self.document_tabs.setCurrentIndex(index)
        if self.active_document_id == self.document_id(index):
            callback()

    def rename_document(self, index, name=None):
        if self.busy or index < 0:
            return
        self.document_tabs.setCurrentIndex(index)
        if self.active_document_id != self.document_id(index):
            return
        if name is None:
            name = NameDialog.ask(
                self,
                "Rename workflow",
                self.path.stem if self.path else self.name.text(),
                "Saved files are renamed in their current folder. Your unsaved changes stay in this tab.",
            )
        if name is None:
            return
        name = name.strip()
        if (
            not name
            or len(name) > 120
            or name in (".", "..")
            or any(c in name for c in ("/", "\\", "\x00"))
        ):
            self.show_error("Choose a name containing 1–120 characters, without folder separators.")
            return
        try:
            old = self.path
            if old is not None:
                new = old.with_name(name + ".json")
                if new != old:
                    if new.exists() or any(
                        doc.path and doc.path.resolve() == new.resolve()
                        for key, doc in self.documents.items()
                        if key != self.active_document_id
                    ):
                        raise ValueError(
                            "A workflow with that filename already exists. Choose a different name."
                        )
                    old.rename(new)
                    self.path = new
                    self.documents[self.active_document_id].path = new
                    self.library_entries.pop(str(old), None)
                    self.preferences.recent_scripts = [
                        p for p in self.preferences.recent_scripts if p != str(old)
                    ]
            self.name.setText(name)
            self.edited()
            if self.path:
                self.remember_workflow(self.path, self.script())
            self.status.setText(
                "Workflow renamed"
                + (" · save to keep the updated title in the file" if self.dirty() else "")
            )
        except (OSError, ValueError) as exc:
            self.show_error(str(exc))

    def close_other_documents(self, index):
        keep = self.document_id(index)
        for other in range(self.document_tabs.count() - 1, -1, -1):
            if self.document_id(other) != keep:
                count = self.document_tabs.count()
                self.close_document(other)
                if self.document_tabs.count() == count:
                    break
        for remaining in range(self.document_tabs.count()):
            if self.document_id(remaining) == keep:
                self.document_tabs.setCurrentIndex(remaining)
                break

    def load_script(self, script, path=None, recovery=None):
        if self.busy:
            return
        script = script.validate().migrate_note_cards()
        if not self.stash_document():
            return
        if path is not None:
            path = Path(path)
            for index in range(self.document_tabs.count()):
                doc = self.documents[self.document_id(index)]
                if doc.path is not None and doc.path.resolve() == path.resolve():
                    self.document_tabs.setCurrentIndex(index)
                    return
        if len(self.documents) >= 64:
            self.show_error("Close a workflow tab before opening more (64 tabs maximum)")
            return
        identifier = uuid4().hex
        stack = QUndoStack(self)
        stack.setUndoLimit(50)
        self.undo.addStack(stack)
        doc = WorkflowDocument(
            script,
            stack,
            script.to_dict(),
            Path(recovery) if recovery else self.config_dir / f"recovery-{identifier}.json",
            path,
        )
        if recovery is not None:
            doc.saved = Script().to_dict()
        self.documents[identifier] = doc
        self.document_tabs.blockSignals(True)
        index = self.document_tabs.addTab(script.name)
        self.document_tabs.setTabData(index, identifier)
        self.document_tabs.setCurrentIndex(index)
        self.document_tabs.blockSignals(False)
        self.activate_document(index, stash=False)

    def activate_document(self, index, stash=True):
        identifier = self.document_id(index)
        if identifier is None or identifier == self.active_document_id or self.busy:
            return
        if stash and not self.stash_document():
            for current in range(self.document_tabs.count()):
                if self.document_id(current) == self.active_document_id:
                    self.document_tabs.blockSignals(True)
                    self.document_tabs.setCurrentIndex(current)
                    self.document_tabs.blockSignals(False)
                    break
            return
        self.group_inspector.select(None, None)
        self.active_document_id = identifier
        doc = self.documents[identifier]
        self.undo.setActiveStack(doc.undo)
        self.model.undo = doc.undo
        self.recovery_path = doc.recovery
        self.last_run = None
        self.workflow.canvas.set_execution({})
        self.workflow.run_summary.hide()
        self.model.execution_trace = None
        self.load_script_view(doc.script, doc.path)
        self.saved_snapshot = doc.saved
        self.loading = True
        view = doc.view
        if view:
            for widget, value in (
                (self.speed, view["speed"]),
                (self.repeats, view["repeats"]),
                (self.countdown, view["countdown"]),
                (self.gap, view["gap"]),
            ):
                widget.setValue(value)
            self.test_mode.setChecked(view["test"])
            self.mode.setCurrentIndex(view["mode"])
            self.activate_target.setChecked(view.get("activate_target", True))
            target = self.target_index(view["target"])
            if target < 0 and view["mode"] == 0 and view["target"] is not None:
                self.target.addItem("Unavailable · " + view["target"].title, view["target"])
                target = self.target.count() - 1
            self.target.setCurrentIndex(max(0, target))
            self.workflow.layout_choice.setCurrentIndex(view["layout"])
            self.workflow.follow_btn.setChecked(view.get("follow", True))
            self.navigate(0, 1 if view["events"] else 0)
            self.set_table_rows(view["selection"])
            indices = {
                i
                for i, b in enumerate(self.blocks)
                if any(b.start <= r < b.end for r in view["selection"])
            }
            self.select_blocks(
                [self.blocks[i] for i in sorted(indices)],
                open_inspector=False,
                preserve_table=view["events"],
            )
            identity = view.get("group")
            if identity in self.model.groups:
                self.group_inspector.select(identity, self.model.groups[identity])
            self.inspector_panel.setVisible(view["inspector"])
            self.inspector_stack.setCurrentIndex(view["inspector_tab"])
            self.inspector_buttons[view["inspector_tab"]].setChecked(True)
        self.loading = False
        self.last_run = doc.last_run
        if self.last_run:
            self.render_playback(self.last_run)
            self.workflow.canvas.camera.stop()  # Restore the document's own viewport below.
        self.edited()

        def restore_view():
            if self.active_document_id != identifier:
                return
            canvas = self.workflow.canvas
            if view:
                canvas.setTransform(view["transform"])
                canvas.queue_reflow()
                canvas.horizontalScrollBar().setValue(view["horizontal"])
                canvas.verticalScrollBar().setValue(view["vertical"])
                canvas.reveal_requested = False
                canvas.zoomChanged.emit(round(canvas.transform().m11() * 100))
            else:
                canvas.fit()

        QTimer.singleShot(0, self, restore_view)

    def close_document(self, index):
        if self.busy or index < 0:
            return
        identifier = self.document_id(index)
        previous = self.active_document_id
        self.document_tabs.setCurrentIndex(index)
        if self.active_document_id != identifier:
            return
        if not self.confirm_discard():
            for other in range(self.document_tabs.count()):
                if self.document_id(other) == previous:
                    self.document_tabs.setCurrentIndex(other)
                    break
            return
        doc = self.documents.pop(identifier)
        try:
            doc.recovery.unlink(missing_ok=True)
        except OSError as exc:
            self.show_error(f"Could not clear recovery file: {exc}")
        self.active_document_id = None
        self.document_tabs.blockSignals(True)
        self.document_tabs.removeTab(index)
        self.document_tabs.blockSignals(False)
        self.undo.removeStack(doc.undo)
        doc.undo.deleteLater()
        if self.document_tabs.count():
            self.activate_document(self.document_tabs.currentIndex(), stash=False)
        else:
            self.load_script(Script())

    def confirm_close_documents(self):
        if not self.stash_document():
            return False
        for index in range(self.document_tabs.count()):
            self.document_tabs.setCurrentIndex(index)
            if not self.confirm_discard():
                return False
        return True

    def recover_documents(self):
        files = sorted(self.config_dir.glob("recovery-*.json"))
        legacy = self.config_dir / "recovery.json"
        if legacy.exists():
            files.append(legacy)
        if not files:
            return
        try:
            recovered = [(path, storage.load(path)) for path in files[:64]]
            if (
                QMessageBox.question(
                    self, "Recover workflows", f"Restore {len(recovered)} unsaved workflow(s)?"
                )
                == QMessageBox.Yes
            ):
                remove_initial = (
                    self.document_tabs.count() == 1 and not self.model.steps and not self.dirty()
                )
                for path, script in recovered:
                    self.load_script(script, recovery=path)
                    if remove_initial:
                        self.close_document(0)
                        remove_initial = False
        except (OSError, ValueError) as exc:
            self.show_error(f"Could not recover workflows: {exc}")
