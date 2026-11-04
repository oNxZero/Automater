"""Searchable picker for live windows; application files are never requested."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from .compatibility import kde_desktop, session_type
from .open_windows import DesktopWindow, matching_x11
from .theme import icon
from .widgets import button, label


class WindowPicker(QDialog):
    def __init__(self, parent, refresh):
        super().__init__(parent)
        self.setWindowTitle("Choose an open window")
        self.setMinimumSize(540, 440)
        self.resize(640, 540)
        self.choice = None
        self.refresh = refresh
        self.mode = parent.mode.currentIndex()
        self.x11_windows = parent.x11_targets
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(label("Choose an open window", "heading"))
        layout.addWidget(
            label(
                "Choose from windows in your separate game session."
                if self.mode == 2
                else "Find your game or app by its window title or application name."
            )
        )
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search open windows…")
        self.search.setAccessibleName("Search open windows")
        self.search.textChanged.connect(self.filter_windows)
        search_row.addWidget(self.search)
        search_row.addWidget(button("Refresh", self.refresh, "ghost", glyph="refresh"))
        layout.addLayout(search_row)
        self.list = QListWidget()
        self.list.setSpacing(4)
        self.list.setAccessibleName("Open application windows")
        self.list.currentItemChanged.connect(self.selection_changed)
        self.list.itemDoubleClicked.connect(lambda *_: self.accept_choice())
        layout.addWidget(self.list, 1)
        self.status = label("")
        layout.addWidget(self.status)
        self.hint = label("")
        self.hint.setMinimumHeight(42)
        layout.addWidget(self.hint)
        actions = QHBoxLayout()
        if self.mode == 0:
            actions.addWidget(button("Use any active window", self.accept, "ghost"))
        actions.addStretch()
        actions.addWidget(button("Cancel", self.reject, "ghost"))
        self.use = button("Use window", self.accept_choice, "primary", glyph="check")
        self.use.setDefault(True)
        self.use.setEnabled(False)
        actions.addWidget(self.use)
        layout.addLayout(actions)
        self.search.setFocus()

    def set_windows(self, windows, error=""):
        selected = self.list.currentItem()
        previous = selected.data(Qt.UserRole) if selected else None
        self.list.clear()
        self.x11_windows = self.parent().x11_targets
        for window in windows:
            app = " · ".join(window.wm_class) or "Application"
            item = QListWidgetItem(f"{window.title}\n{app} · PID {window.pid}")
            item.setIcon(QIcon.fromTheme(app, icon("target")))
            item.setData(Qt.UserRole, window)
            item.setToolTip(window.title)
            self.list.addItem(item)
            if previous and (window.id, window.pid) == (previous.id, previous.pid):
                self.list.setCurrentItem(item)
        self.filter_windows()
        if error:
            self.status.setText(error)

    def filter_windows(self):
        query = self.search.text().strip().casefold()
        visible = []
        for index in range(self.list.count()):
            item = self.list.item(index)
            item.setHidden(query not in item.text().casefold())
            if not item.isHidden():
                visible.append(item)
        if self.list.currentItem() not in visible:
            self.list.setCurrentItem(visible[0] if visible else None)
        self.status.setText(
            f"{len(visible)} open window{'s' if len(visible) != 1 else ''}"
            if visible
            else "No matching windows. Open your app, then refresh."
        )
        if not visible and session_type() == "wayland" and not kde_desktop():
            self.status.setText(
                "This desktop does not expose native Wayland windows to Studio. X11/Xwayland windows can appear here; use Any active window for other apps, then focus your game during the countdown."
            )
        self.selection_changed()

    def selection_changed(self, *_):
        item = self.list.currentItem()
        window = item.data(Qt.UserRole) if item and not item.isHidden() else None
        if not hasattr(self, "use"):
            return
        self.use.setEnabled(window is not None)
        desktop_only = (
            window
            and isinstance(window, DesktopWindow)
            and matching_x11(window, self.x11_windows) is None
        )
        self.use.setText(
            "Use on active desktop" if self.mode == 1 and desktop_only else "Use window"
        )
        self.hint.setText(
            "Independent game session · your desktop mouse and keyboard remain free."
            if self.mode == 2
            else "This window needs desktop playback. Studio can bring it forward automatically after the countdown. Your normal pointer is used."
            if self.mode == 1 and desktop_only
            else "Background delivery · some apps and games ignore these events."
            if self.mode == 1
            else "Studio can bring this window forward after the countdown. Desktop playback uses your normal pointer and stops if you switch away. Independent input needs a background mode."
        )

    def accept_choice(self):
        item = self.list.currentItem()
        if item and not item.isHidden():
            self.choice = item.data(Qt.UserRole)
            self.accept()
