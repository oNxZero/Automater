"""Built-in appearance presets; independent of Qt and portable workflow data."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str
    base: str
    panel: str
    border: str
    text: str
    muted: str
    accent: str
    blue: str
    success: str
    danger: str
    warning: str = "#e8c58a"


# The named palettes follow the user's original Moonlight theme gallery.
PALETTES = {
    "studio": Palette(
        "Studio",
        "#11131e",
        "#1b1e2e",
        "#494d64",
        "#e2e5f4",
        "#9199b3",
        "#b5a4fa",
        "#83b8f2",
        "#75d6c0",
        "#f2a3bc",
    ),
    "moonlight": Palette(
        "Moonlight",
        "#181926",
        "#24273a",
        "#494d64",
        "#cad3f5",
        "#a5adcb",
        "#8caaee",
        "#8caaee",
        "#a6da95",
        "#ed8796",
    ),
    "obsidian": Palette(
        "Obsidian",
        "#000000",
        "#0a0a0a",
        "#343439",
        "#ffffff",
        "#a1a1aa",
        "#c0c0c0",
        "#93b4ec",
        "#4ade80",
        "#f87171",
    ),
    "crimson": Palette(
        "Crimson",
        "#0f0808",
        "#241616",
        "#522929",
        "#ffe6e6",
        "#d6a9a9",
        "#ff6b6b",
        "#9bbcf5",
        "#6ed9ad",
        "#ff8585",
    ),
    "dracula": Palette(
        "Dracula",
        "#191a21",
        "#282a36",
        "#6272a4",
        "#f8f8f2",
        "#b1afc9",
        "#bd93f9",
        "#8be9fd",
        "#50fa7b",
        "#ff7979",
    ),
    "viper": Palette(
        "Viper",
        "#050f08",
        "#0a1f11",
        "#285339",
        "#e6ffee",
        "#9abdac",
        "#4ade80",
        "#8bbfea",
        "#4ade80",
        "#fb8585",
    ),
    "nord": Palette(
        "Nord",
        "#1c2128",
        "#2e3440",
        "#59667c",
        "#eceff4",
        "#a4b0c6",
        "#88c0d0",
        "#81a1c1",
        "#a3be8c",
        "#df8d96",
    ),
    "sakura": Palette(
        "Sakura",
        "#191724",
        "#232136",
        "#514663",
        "#e0def4",
        "#b2a5c5",
        "#eb8aab",
        "#9ccfd8",
        "#9ccfd8",
        "#f28faa",
    ),
    "solaris": Palette(
        "Solaris",
        "#0a0907",
        "#1f1c16",
        "#594a35",
        "#fffbeb",
        "#c6b68d",
        "#fbbf24",
        "#9ec2f3",
        "#6dd3aa",
        "#fb8da1",
    ),
    "catppuccin": Palette(
        "Catppuccin",
        "#11111b",
        "#1e1e2e",
        "#585b70",
        "#cdd6f4",
        "#a6adc8",
        "#b4befe",
        "#89b4fa",
        "#a6e3a1",
        "#f38ba8",
    ),
    "daylight": Palette(
        "Daylight",
        "#f2f4fa",
        "#ffffff",
        "#b7bfd2",
        "#202639",
        "#59657d",
        "#6651bd",
        "#286ba1",
        "#247260",
        "#b13d62",
        "#946013",
    ),
}


def validate_appearance(name, overrides):
    if not isinstance(name, str) or name not in PALETTES:
        raise ValueError("Choose an available appearance theme")
    if not isinstance(overrides, dict) or set(overrides) - {"accent", "base"}:
        raise ValueError("Unknown theme color setting")
    if any(
        not isinstance(c, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", c)
        for c in overrides.values()
    ):
        raise ValueError("Theme colors must use #RRGGBB")
