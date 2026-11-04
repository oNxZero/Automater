"""Explicit desktop cursor positioning. Never treats Xwayland warps as native Wayland warps."""

import json
import os
import shutil
import subprocess


def coordinate(value):
    if type(value) is not int or not -32768 <= value <= 32767:
        raise ValueError("Coordinates must be whole numbers between −32768 and 32767")
    return value


def desktop_pointer():
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
        return HyprlandPointer()
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError(
            "Exact desktop starting coordinates currently require X11 or Hyprland. "
            "Other Wayland desktops can still replay relative input with reset disabled."
        )
    return X11Pointer()


def capability():
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
        return True, "Hyprland desktop coordinates (logical pixels)"
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        return (
            False,
            "Exact desktop reset is available on X11 and Hyprland. Other Wayland desktops support relative replay without reset.",
        )
    return True, "X11 desktop screen coordinates"


class X11Pointer:
    def __init__(self):
        from Xlib import display

        self.connection = display.Display()
        self.root = self.connection.screen().root

    def position(self):
        point = self.root.query_pointer()
        return point.root_x, point.root_y

    def validate(self, point):
        x, y = map(coordinate, point)
        geometry = self.root.get_geometry()
        if not 0 <= x < geometry.width or not 0 <= y < geometry.height:
            raise ValueError("Starting point is outside the X11 desktop")

    def move(self, point):
        self.validate(point)
        self.root.warp_pointer(*point)
        self.connection.sync()
        if self.position() != tuple(point):
            raise RuntimeError(
                "The desktop did not accept the starting point. Release pointer capture and try again."
            )

    def close(self):
        self.connection.close()


class HyprlandPointer:
    @staticmethod
    def command(*args, as_json=True):
        command = ["hyprctl", "-j", *args] if as_json else ["hyprctl", *args]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=2, check=True)
            return json.loads(result.stdout) if as_json else result.stdout.strip()
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise RuntimeError(f"Could not communicate with Hyprland: {exc}") from exc

    def position(self):
        point = self.command("cursorpos")
        return round(point["x"]), round(point["y"])

    def validate(self, point):
        x, y = map(coordinate, point)
        for monitor in self.command("monitors"):
            if monitor.get("disabled"):
                continue
            width, height = monitor["width"], monitor["height"]
            if monitor.get("transform", 0) % 2:
                width, height = height, width
            scale = monitor.get("scale", 1)
            if scale <= 0:
                continue
            if (
                monitor["x"] <= x < monitor["x"] + width / scale
                and monitor["y"] <= y < monitor["y"] + height / scale
            ):
                return
        raise ValueError("Starting point is outside the enabled Hyprland monitors")

    def move(self, point):
        self.validate(point)
        result = self.command("dispatch", "movecursor", str(point[0]), str(point[1]), as_json=False)
        if result != "ok":
            raise RuntimeError(f"Hyprland rejected the cursor move: {result}")
        actual = self.position()
        if any(abs(a - b) > 1 for a, b in zip(actual, point)):
            raise RuntimeError(
                "The pointer could not reach the starting point. Release pointer capture and try again."
            )

    def close(self):
        pass
