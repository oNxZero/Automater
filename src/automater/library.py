"""Discover saved workflows in known folders without blocking the editor."""

import threading
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QListWidgetItem

from . import storage
from .theme import icon


def scan_workflows(roots, recent=(), cancel=None):
    paths = {Path(p) for p in recent}
    for root in roots:
        try:
            for index, path in enumerate(Path(root).iterdir()):
                if (cancel and cancel.is_set()) or index >= 5000 or len(paths) >= 5000:
                    break
                if path.suffix.lower() == ".json" and not path.name.startswith("recovery"):
                    paths.add(path)
        except OSError:
            continue
        if len(paths) >= 5000:
            break
    entries = []
    for path in sorted(paths, key=str):
        if cancel and cancel.is_set():
            break
        try:
            if path.name.startswith("recovery") or path.name == "preferences.json":
                continue
            script = storage.load(path)
            entries.append((str(path.resolve()), script.name, len(script.steps)))
        except (OSError, ValueError):
            continue
    return entries


class LibraryMixin:
    def library_roots(self):
        roots = {self.library_dir, *(Path(p) for p in self.preferences.library_folders)}
        if self.preferences.script_directory:
            roots.add(Path(self.preferences.script_directory))
        roots.update(Path(p).parent for p in self.preferences.recent_scripts)
        roots.update(doc.path.parent for doc in self.documents.values() if doc.path)
        if not self.demo:
            roots.add(Path.cwd())  # Older releases saved directly beside start.sh.
        return sorted(roots, key=str)

    def remember_workflow(self, path, script):
        path = str(Path(path).resolve())
        self.preferences.recent_scripts = [path] + [
            p for p in self.preferences.recent_scripts if p != path
        ][:127]
        self.library_entries[path] = (path, script.name, len(script.steps))
        self.save_preferences()
        self.render_library()

    def add_library_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Add workflow folder", str(self.script_dialog_directory())
        )
        if path:
            folder = str(Path(path).resolve())
            self.preferences.library_folders = list(
                dict.fromkeys([*self.preferences.library_folders, folder])
            )[-64:]
            self.save_preferences()
            self.refresh_library()

    def refresh_library(self):
        if self.library_shutdown:
            return
        if self.library_scan_pending:
            self.library_scan_requested = True
            return
        self.library_generation += 1
        generation = self.library_generation
        roots, recent = self.library_roots(), list(self.preferences.recent_scripts)
        self.library_scan_pending = True
        self.filter_library()

        def scan():
            entries = scan_workflows(roots, recent, self.library_stop)
            if not self.library_stop.is_set():
                self.bridge.library_ready.emit(generation, entries)

        threading.Thread(target=scan, daemon=True).start()

    def library_scanned(self, generation, entries):
        if self.library_shutdown or generation != self.library_generation:
            return
        self.library_scan_pending = False
        if self.library_scan_requested:
            self.library_scan_requested = False
            self.refresh_library()
            return
        self.library_entries = {entry[0]: entry for entry in entries}
        self.render_library()

    def render_library(self):
        self.library.clear()
        for path, name, count in sorted(
            self.library_entries.values(), key=lambda entry: Path(entry[0]).stem.casefold()
        ):
            metadata = [] if name == Path(path).stem else [name]
            metadata.extend((f"{count:,} event{'s' if count != 1 else ''}", Path(path).parent.name))
            text = Path(path).stem + "\n" + " · ".join(metadata)
            item = QListWidgetItem(text)
            item.setIcon(icon("flow", "#b5a4fa"))
            item.setData(Qt.UserRole, path)
            item.setData(Qt.UserRole + 1, path + " " + name)
            item.setToolTip(path)
            self.library.addItem(item)
        self.filter_library()

    def filter_library(self):
        query = self.library_search.text().strip().casefold()
        visible = 0
        for index in range(self.library.count()):
            item = self.library.item(index)
            item.setHidden(query not in (item.text() + " " + item.data(Qt.UserRole + 1)).casefold())
            visible += not item.isHidden()
        self.library_empty.setVisible(visible == 0)
        self.library_empty.setText(
            "Finding saved workflows…"
            if self.library_scan_pending
            else f"No workflows match “{self.library_search.text()}”."
            if query
            else "No saved workflows found. Add the folder containing your JSON files, or save your first workflow."
        )
