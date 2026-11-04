"""Instant application-wide appearance, kept outside portable workflow files."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .palettes import PALETTES
from .widgets import button, label


class ThemeCard(QPushButton):
    def __init__(self, identity, callback):
        super().__init__()
        self.identity = identity
        self.setObjectName("themeCard")
        self.setCheckable(True)
        self.setMinimumSize(156, 82)
        self.setAccessibleName(PALETTES[identity].name + " theme")
        self.setToolTip("Apply " + PALETTES[identity].name)
        self.clicked.connect(lambda: callback(identity, {}))

    def paintEvent(self, event):
        p = theme.palette(self.identity, {})
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(
            QPen(
                QColor(
                    p.accent
                    if self.isChecked() or self.hasFocus() or self.underMouse()
                    else p.border
                ),
                2 if self.isChecked() else 1,
            )
        )
        painter.setBrush(QColor(p.base))
        painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 9, 9)
        painter.setPen(QColor(p.text))
        painter.drawText(
            self.rect().adjusted(14, 9, -12, -36),
            Qt.AlignVCenter,
            p.name + ("  ✓" if self.isChecked() else ""),
        )
        for i, color in enumerate((p.panel, p.accent, p.blue, p.success, p.danger)):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(14 + i * 25, self.height() - 28, 18, 12, 4, 4)


class AppearanceDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Appearance · Automater")
        self.resize(620, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        layout.addWidget(label("Make it yours", "heading"))
        layout.addWidget(
            label(
                "Choose a theme to apply it instantly. Appearance is remembered on this device; workflow data and group colors stay unchanged."
            )
        )
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 10, 0)
        body.setSpacing(16)
        grid = QGridLayout()
        grid.setSpacing(10)
        self.cards = {}
        for i, identity in enumerate(PALETTES):
            card = ThemeCard(identity, window.apply_appearance)
            grid.addWidget(card, i // 3, i % 3)
            self.cards[identity] = card
        body.addLayout(grid)
        body.addWidget(label("YOUR COLORS", "eyebrow"))
        body.addWidget(
            label(
                "Optionally customize the accent and background. Choosing a gallery theme resets these overrides."
            )
        )
        colors = QHBoxLayout()
        self.accent = button("Accent color…", lambda: self.pick_color("accent"), glyph="spark")
        self.background = button(
            "Background color…", lambda: self.pick_color("base"), glyph="automation"
        )
        colors.addWidget(self.accent)
        colors.addWidget(self.background)
        body.addLayout(colors)
        self.summary = label("")
        body.addWidget(self.summary)
        body.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        actions = QHBoxLayout()
        actions.addWidget(
            button("Reset to Automater", lambda: window.apply_appearance("automater", {}), "ghost")
        )
        actions.addStretch()
        actions.addWidget(button("Done", self.accept, "primary", glyph="check"))
        layout.addLayout(actions)
        self.sync()

    def pick_color(self, field):
        current = getattr(theme.palette(), field)
        selected = QColorDialog.getColor(
            QColor(current),
            self,
            "Choose " + ("background" if field == "base" else "accent") + " color",
        )
        if selected.isValid():
            self.window.apply_appearance(
                self.window.preferences.theme,
                {**self.window.preferences.theme_colors, field: selected.name()},
            )

    def sync(self):
        prefs = self.window.preferences
        for identity, card in self.cards.items():
            card.setChecked(identity == prefs.theme)
        p = theme.palette()
        self.summary.setText(
            f"{p.name} · Accent {p.accent} · Background {p.base}"
            + (" · Custom colors" if prefs.theme_colors else "")
        )


class AppearanceMixin:
    def show_appearance(self):
        if self.busy:
            self.show_error("Finish recording or playback before changing appearance.")
            return
        if self.appearance_dialog is None:
            self.appearance_dialog = AppearanceDialog(self)
        self.appearance_dialog.sync()
        self.appearance_dialog.show()
        self.appearance_dialog.raise_()

    def apply_appearance(self, name, overrides=None, persist=True):
        if persist and self.busy:
            self.show_error("Finish recording or playback before changing appearance.")
            return False
        theme.activate(name, overrides)
        self.preferences.theme = name
        self.preferences.theme_colors = dict(overrides or {})
        self.setStyleSheet(theme.stylesheet())
        p = theme.palette()
        palette = QPalette()
        for role, value in (
            (QPalette.Window, p.base),
            (QPalette.WindowText, p.text),
            (QPalette.Base, p.panel),
            (QPalette.AlternateBase, p.base),
            (QPalette.Text, p.text),
            (QPalette.Button, p.panel),
            (QPalette.ButtonText, p.text),
            (QPalette.Highlight, p.accent),
            (QPalette.HighlightedText, theme.resolve_hex("#181424")),
            (QPalette.PlaceholderText, p.muted),
            (QPalette.ToolTipBase, p.panel),
            (QPalette.ToolTipText, p.text),
        ):
            palette.setColor(role, QColor(value))
        self.setPalette(palette)
        self.setWindowIcon(theme.icon("automation", theme.ACCENT))
        for widget in self.findChildren(QPushButton):
            glyph = widget.property("themeGlyph")
            if glyph:
                tone = widget.property("themeTone")
                color = (
                    "#201b2e"
                    if tone == "primary"
                    else "#f2a3bc"
                    if tone in ("record", "stop")
                    else "#b6b0cd"
                )
                widget.setIcon(theme.icon(glyph, color))
        for widget in self.findChildren(QLabel):
            glyph = widget.property("themeGlyph")
            if glyph:
                size = widget.property("themeSize") or 24
                widget.setPixmap(theme.icon(glyph, theme.ACCENT, size).pixmap(size, size))
        if hasattr(self, "workflow"):
            canvas = self.workflow.canvas
            for item in canvas.scene().items():
                if hasattr(item, "setBrush") and hasattr(item, "text"):
                    item.setBrush(theme.paint_color(theme.MUTED))
            canvas.scene().update()
            self.table.viewport().update()
            self.record_preview.update()
            for i in range(self.library.count()):
                self.library.item(i).setIcon(theme.icon("flow", theme.ACCENT))
        if self.appearance_dialog:
            self.appearance_dialog.sync()
        if persist:
            self.save_preferences()
        return True
