"""Shared native Qt design tokens and small original vector icons."""

import re
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap

from .palettes import PALETTES, validate_appearance

_theme_name = "automater"
_overrides = {}


def mix(a, b, amount):
    a, b = QColor(a), QColor(b)
    amount = max(0, min(1, amount))
    return QColor.fromRgbF(
        *(x + (y - x) * amount for x, y in zip(a.getRgbF()[:3], b.getRgbF()[:3]))
    ).name()


def luminance(value):
    components = QColor(value).getRgbF()[:3]
    channels = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in components]
    return sum(c * w for c, w in zip(channels, (0.2126, 0.7152, 0.0722)))


def contrast(a, b):
    low, high = sorted((luminance(a), luminance(b)))
    return (high + 0.05) / (low + 0.05)


def palette(name=None, overrides=None):
    name = _theme_name if name is None else name
    overrides = _overrides if overrides is None else overrides
    validate_appearance(name, overrides)
    result = PALETTES[name]
    if "base" in overrides:
        base = overrides["base"]
        light = contrast(base, "#11131e") > contrast(base, "#ffffff")
        reference = (
            PALETTES["daylight"] if light else PALETTES[name if name != "daylight" else "automater"]
        )
        text = reference.text
        if contrast(text, base) < 4.5:
            text = max(("#000000", "#ffffff"), key=lambda color: contrast(color, base))
        muted = reference.muted
        for _ in range(24):
            if contrast(muted, base) >= 4.5:
                break
            muted = mix(muted, text, 0.2)
        result = replace(
            result,
            base=base,
            panel=mix(base, "#ffffff", 0.65) if light else mix(base, reference.accent, 0.07),
            border=mix(base, "#202639" if light else "#aab3cc", 0.28),
            text=text,
            muted=muted,
            blue=reference.blue,
            success=reference.success,
            danger=reference.danger,
            warning=reference.warning,
        )
    if "accent" in overrides:
        result = replace(result, accent=overrides["accent"])
    return result


def activate(name, overrides=None):
    global _theme_name, _overrides
    validate_appearance(name, overrides or {})
    _theme_name, _overrides = name, dict(overrides or {})
    resolve_hex.cache_clear()
    _icon.cache_clear()


@lru_cache(maxsize=512)
def resolve_hex(value):
    if _theme_name == "automater" and not _overrides:
        return value
    p = palette()
    exact = {
        "#11131e": p.base,
        "#1b1e2e": p.panel,
        "#1c2032": p.panel,
        "#131724": mix(p.base, p.panel, 0.2),
        "#e2e5f4": p.text,
        "#d8ddef": p.text,
        "#bbc2d9": p.text,
        "#9199b3": p.muted,
        "#5d5877": p.muted,
        "#b5a4fa": p.accent,
        "#83b8f2": p.blue,
        "#75d6c0": p.success,
        "#f2a3bc": p.danger,
        "#e8c58a": p.warning,
        "#181424": "#151722"
        if contrast(p.accent, "#151722") > contrast(p.accent, "#ffffff")
        else "#ffffff",
    }
    for key in ("#201b2e", "#211b30"):
        exact[key] = exact["#181424"]
    if value in exact:
        return exact[value]
    backgrounds = {
        "#243e39": p.success,
        "#593245": p.danger,
        "#2b4059": p.blue,
        "#54452d": p.warning,
        "#364463": p.blue,
    }
    if value in backgrounds:
        return mix(p.panel, backgrounds[value], 0.16)
    c = QColor(value)
    if c.valueF() < 0.48:
        return mix(p.base, p.border, (c.valueF() - 0.10) / 0.35)
    hue, saturation, brightness, _ = c.getHsvF()
    if 0.70 < hue < 0.85 and saturation > 0.13:
        return mix(p.accent, p.text, max(0, brightness - 0.85))
    return p.text if brightness > 0.83 else p.muted


def paint_color(*args):
    if len(args) == 1 and isinstance(args[0], str) and args[0].startswith("#"):
        return QColor(resolve_hex(args[0].lower()))
    return QColor(*args)


def legible_group_color(value):
    """Improve label contrast without changing the group's saved custom color."""
    background = palette().panel
    target = "#11131e" if luminance(background) > 0.4 else "#ffffff"
    color = value
    for _ in range(12):
        if contrast(color, background) >= 3:
            break
        color = mix(color, target, 0.15)
    return QColor(color)


ACCENT = "#b5a4fa"
TEXT = "#e2e5f4"
MUTED = "#9199b3"
BASE = "#11131e"
PANEL = "#1b1e2e"
COLORS = {
    "note": "#e8c58a",
    "key": "#b5a4fa",
    "mouse": "#83b8f2",
    "wait": "#e8c58a",
    "move": "#75d6c0",
    "scroll": "#83b8f2",
    "group": "#9199b3",
}

PATHS = {
    "note": '<path d="M4 2h12v12l-4 4H4Zm8 16v-4h4M7 6h6m-6 4h6"/>',
    "group": '<rect x="2" y="3" width="16" height="14" rx="3" stroke-dasharray="3 2"/><path d="M6 7h8m-8 4h5"/>',
    "press": '<rect x="3" y="10" width="14" height="8" rx="2"/><path d="M10 2v10m-3-3 3 3 3-3"/>',
    "release": '<rect x="3" y="10" width="14" height="8" rx="2"/><path d="M10 11V2M7 5l3-3 3 3"/>',
    "select": '<path d="M3 3h5m-5 0v5m14-5h-5m5 0v5M3 17h5m-5 0v-5m14 5h-5m5 0v-5"/>',
    "automation": '<g stroke-width="1.5"><path d="M7.25 7h5.25M15.75 11.25V13a3.5 3.5 0 0 1-3.5 3.5h-5A3.5 3.5 0 0 1 3.75 13v-1.75M2 12.75 3.75 11 5.5 12.75"/></g><circle cx="5" cy="7" r="2.25" fill="currentColor" stroke="none"/><path d="m12.5 3.75 5 3.25-5 3.25Z" fill="currentColor" stroke="currentColor" stroke-width=".6"/>',
    "flow": '<rect x="2" y="7" width="5" height="6" rx="1.3"/><rect x="13" y="7" width="5" height="6" rx="1.3"/><path d="M7 10h6m-2-2 2 2-2 2"/>',
    "list": '<path d="M7 5h11M7 10h11M7 15h11M2 5h1M2 10h1M2 15h1"/>',
    "library": '<rect x="3" y="3" width="14" height="14" rx="2"/><path d="M3 7h14m-9 0v10m3-6h3m-3 3h3"/>',
    "settings": '<path d="m8 2-.7 2-2 .8-2-.6-1.5 2.6 1.5 1.6v2.3l-1.5 1.6 1.5 2.6 2-.6 2 .8.7 2h3l.7-2 2-.8 2 .6 1.5-2.6-1.5-1.6V8.4l1.5-1.6-1.5-2.6-2 .6-2-.8-.7-2Z"/><circle cx="9.5" cy="9.5" r="3"/>',
    "play": '<path d="m6 3 11 7-11 7Z" fill="currentColor" stroke="none"/>',
    "pause": '<path d="M6 3h3v14H6Zm5 0h3v14h-3Z" fill="currentColor" stroke="none"/>',
    "stop": '<rect x="4" y="4" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
    "record": '<circle cx="10" cy="10" r="6" fill="currentColor" stroke="none"/>',
    "plus": '<path d="M10 4v12M4 10h12"/>',
    "minus": '<path d="M4 10h12"/>',
    "right": '<path d="m8 5 5 5-5 5"/>',
    "left": '<path d="m12 5-5 5 5 5"/>',
    "down": '<path d="m5 8 5 5 5-5"/>',
    "key": '<rect x="2" y="5" width="16" height="11" rx="2"/><path d="M5 8h1m3 0h1m3 0h1m-9 3h1m3 0h1m3 0h1m-8 2h6"/>',
    "mouse": '<rect x="5" y="2" width="10" height="16" rx="5"/><path d="M5 8h10m-5-6v6"/>',
    "wait": '<circle cx="10" cy="10" r="7"/><path d="M10 6v5l3 2"/>',
    "move": '<path d="M10 2v16M2 10h16M7 5l3-3 3 3M7 15l3 3 3-3M5 7l-3 3 3 3m10-6 3 3-3 3"/>',
    "scroll": '<path d="M7 7l3-4 3 4M10 3v14m-3-4 3 4 3-4"/>',
    "save": '<path d="M4 2h11l3 3v13H2V2Zm2 0v5h7V2M6 18v-7h8v7"/>',
    "open": '<path d="M2 7V4h6l2 3h8l-3 10H2Zm0 0h8"/>',
    "check": '<path d="m4 10 4 4 8-8"/>',
    "trash": '<path d="M3 5h14M8 2h4l1 3M5 5l1 13h8l1-13M8 8v7m4-7v7"/>',
    "copy": '<rect x="6" y="6" width="11" height="12" rx="2"/><path d="M3 14V2h10"/>',
    "undo": '<path d="M3 8h9a5 5 0 0 1 0 10M3 8l4-4M3 8l4 4"/>',
    "redo": '<path d="M17 8H8a5 5 0 0 0 0 10m9-10-4-4m4 4-4 4"/>',
    "refresh": '<path d="M16 7a6 6 0 1 0 0 6m0-10v4h-4"/>',
    "target": '<rect x="2" y="3" width="16" height="12" rx="2"/><path d="M7 18h6m-3-3v3M2 7h16"/>',
    "info": '<circle cx="10" cy="10" r="7"/><path d="M10 9v5m0-8v.1"/>',
    "close": '<path d="m5 5 10 10M5 15 15 5"/>',
    "fit": '<path d="M7 3H3v4m10-4h4v4M3 13v4h4m10-4v4h-4"/>',
    "search": '<circle cx="8" cy="8" r="5"/><path d="m12 12 5 5"/>',
    "spark": '<path d="m10 2 2.2 5.8L18 10l-5.8 2.2L10 18l-2.2-5.8L2 10l5.8-2.2Z"/>',
}


def icon(name, color=MUTED, size=20, *, resolved=False):
    return _icon(name, color.lower() if resolved else resolve_hex(color.lower()), size)


def app_icon():
    """Use the same full-color mark as the desktop entry and repository."""
    return QIcon(str(Path(__file__).parent / "assets/automater.svg"))


def shadow_color():
    return QColor(5, 7, 15, 22 if luminance(palette().text) < luminance(palette().base) else 70)


@lru_cache(maxsize=128)
def _icon(name, color, size):
    data = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 20 20" color="{color}" fill="none" stroke="{color}" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</svg>'
    )
    pixmap = QPixmap()
    pixmap.loadFromData(QByteArray(data.encode()), "SVG")
    return QIcon(pixmap)


def font(size=10, bold=False):
    result = QFont("Inter", size)
    result.setStyleHint(QFont.SansSerif)
    result.setWeight(QFont.DemiBold if bold else QFont.Normal)
    return result


STYLE = """
QLabel#saveState {color: #e8c58a; background: #302b30; border: 1px solid #514354; border-radius: 5px; padding: 3px 8px; font-size: 11px;}
QWidget { color: #e2e5f4; font-family: 'Inter', 'Noto Sans', sans-serif; font-size: 13px; }
QTabBar { background: transparent; }
QTabBar::tab { background: #171b29; color: #9199b3; border: 1px solid #2d3248;
    border-radius: 7px; padding: 8px 14px; padding-right: 24px; margin-right: 5px; min-width: 90px; max-width: 240px; }
QTabBar::tab:selected { background: #302b47; color: #e2e5f4; border-color: #5a4b83; }
QTabBar::tab:hover { background: #25283b; }
QMainWindow, QWidget#app { background: #11131e; }
QWidget#sidebar { background: #161925; border-right: 1px solid #282d40; }
QFrame#card, QFrame#inspector { background: #1b1e2e; border: 1px solid #2d3248; border-radius: 12px; }
QFrame#hero { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #24243b,stop:1 #1b2033);
              border: 1px solid #393954; border-radius: 14px; }
QFrame#notice { background: #1e2436; border: 1px solid #303b54; border-radius: 9px; }
QFrame#transport { background: #1b1e2e; border: 1px solid #2d3248; border-radius: 12px; }
QLabel { background: transparent; border: none; }
QLabel#brand { font-size: 18px; font-weight: 800; letter-spacing: .2px; }
QLabel#title { font-size: 25px; font-weight: 700; }
QLabel#heading { font-size: 17px; font-weight: 700; }
QLabel#eyebrow { color: #8991ad; font-size: 10px; font-weight: 700; letter-spacing: 1.2px; }
QLabel#muted { color: #9199b3; font-size: 12px; }
QLabel#body { color: #bbc2d9; }
QLabel#badge { background: #2b2945; color: #c5b8ff; border: 1px solid #443d66;
               padding: 4px 9px; border-radius: 7px; font-size: 10px; font-weight: 600; }
QLabel#status { color: #a9b2cd; font-size: 12px; padding: 2px; }
QPushButton { background: #252a3d; border: 1px solid #373d55; border-radius: 7px;
              padding: 8px 13px; font-weight: 600; min-height: 18px; }
QPushButton#themeCard { min-height: 82px; min-width: 156px; padding: 0; }
QPushButton:hover { background: #30354d; border-color: #6e668e; }
QPushButton:pressed { background: #39354e; }
QPushButton:focus { border: 1px solid #b5a4fa; }
QPushButton:disabled { background: #1b1e2b; border-color: #292e40; color: #646c85; }
QPushButton#primary { background: #b5a4fa; color: #181424; border-color: #b5a4fa; }
QPushButton#primary:hover { background: #c7b9ff; }
QPushButton#primary:disabled { background: #373149; color: #767086; border-color: #373149; }
QPushButton#record { background: #302332; color: #f2a3bc; border-color: #644058; }
QPushButton#record:hover { background: #493044; }
QPushButton#stop { background: transparent; color: #f2a3bc; border-color: #554050; }
QPushButton#ghost { background: transparent; border-color: transparent; color: #a8b0c9; }
QPushButton#ghost:hover { background: #292e42; color: #e2e5f4; }
QPushButton#nav { background: transparent; border: none; text-align: left; color: #929ab5;
                  border-radius: 8px; padding: 11px 14px; }
QPushButton#nav:hover { background: #24283b; color: #d7dcf2; }
QPushButton#nav:checked { background: #302b47; color: #c9bcff; }
QPushButton#segment { background: transparent; border: none; padding: 6px 13px; color: #8e97b3; }
QPushButton#segment:checked { background: #343147; color: #d5caff; }
QFrame#segments { background: #191d2b; border: 1px solid #2d3349; border-radius: 9px; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit {
    background: #141824; border: 1px solid #32394f; border-radius: 7px;
    padding: 8px; selection-background-color: #4d416c; color: #d8ddef; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus {
    border-color: #a18bde; }
QLineEdit#scriptTitle { background: transparent; border: 1px solid transparent;
                      padding: 0; font-size: 25px; font-weight: 700; }
QLineEdit#scriptTitle:hover, QLineEdit#scriptTitle:focus { border-color: #363b52; background: #191d2b; }
QDoubleSpinBox#actionValue, QSpinBox#actionValue, QComboBox#actionKey {
    background: #171b29; border: 1px solid #30374c; border-radius: 9px;
    padding: 9px 12px; font-size: 14px; min-height: 18px; }
QDoubleSpinBox#actionValue:hover, QSpinBox#actionValue:hover, QComboBox#actionKey:hover {
    border-color: #55566f; }
QDoubleSpinBox#actionValue:focus, QSpinBox#actionValue:focus, QComboBox#actionKey:focus {
    border-color: #b5a4fa; background: #191d2b; }
QComboBox#actionKey QLineEdit { background: transparent; border: none; padding: 0; font-size: 14px; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #23283b; border: 1px solid #48435e;
                            selection-background-color: #403655; outline: none; }
QAbstractSpinBox { padding-right: 20px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right;
    width: 18px; background: #2b3044; border-top-right-radius: 6px; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right;
    width: 18px; background: #2b3044; border-bottom-right-radius: 6px; }
QTableView { background: #181c2a; alternate-background-color: #1b2030; border: none;
             border-radius: 10px; gridline-color: #2b3147; selection-background-color: #3b3457; }
QHeaderView::section { background: #222738; color: #9ea8c4; padding: 11px;
                      border: none; border-bottom: 1px solid #343a51; font-size: 11px; font-weight: 600; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { background: #1e2334; border: 1px solid #30374c; border-radius: 9px;
                    padding: 14px; margin-bottom: 8px; }
QListWidget::item:hover { background: #272b40; border-color: #665a82; }
QListWidget::item:selected { background: #312b47; border-color: #9b87ca; }
QCheckBox { spacing: 9px; padding: 3px 0; color: #bfc6dd; }
QCheckBox::indicator { width: 17px; height: 17px; border-radius: 5px;
                      border: 1px solid #4b526c; background: #171b29; }
QCheckBox::indicator:checked { background: #b5a4fa; border-color: #b5a4fa; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #3d435b; min-height: 32px; border-radius: 3px; }
QScrollBar:horizontal { background: #161a28; height: 9px; margin: 2px; }
QScrollBar::handle:horizontal { background: #3d435b; min-width: 32px; border-radius: 3px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QSplitter::handle { background: transparent; width: 12px; }
QToolTip { background: #2b2d44; color: #e2e5f4; border: 1px solid #6a5b8d; padding: 6px; }
QMenu { background: #24283c; border: 1px solid #4a405f; padding: 5px; border-radius: 9px; }
QMenu::item { padding: 8px 20px; border-radius: 5px; }
QMenu::item:selected { background: #43385c; }
QDialog, QMessageBox { background: #1b1e2e; }
QProgressBar { background: #272c40; border: none; border-radius: 2px; max-height: 4px; }
QProgressBar::chunk { background: #b5a4fa; border-radius: 2px; }
"""

STYLE += """
QTabBar::close-button { image: url("@ASSETS@/close.svg"); width: 14px; height: 14px;
    padding: 0; }
QComboBox::down-arrow { image: url("@ASSETS@/chevron-down.svg"); width: 12px; height: 12px; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url("@ASSETS@/chevron-up.svg"); width: 12px; height: 12px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url("@ASSETS@/chevron-down.svg"); width: 12px; height: 12px; }
QCheckBox::indicator:checked { image: url("@ASSETS@/check.svg"); }
""".replace("@ASSETS@", (Path(__file__).parent / "assets").as_posix())


def stylesheet():
    result = re.sub(r"#[0-9a-fA-F]{6}\b", lambda match: resolve_hex(match.group().lower()), STYLE)
    if luminance(palette().text) < luminance(palette().base):
        for asset in ("close", "chevron-down", "chevron-up"):
            result = result.replace(f"/{asset}.svg", f"/{asset}-light.svg")
    if resolve_hex("#181424") == "#ffffff":
        result = result.replace("/check.svg", "/check-light.svg")
    return result
