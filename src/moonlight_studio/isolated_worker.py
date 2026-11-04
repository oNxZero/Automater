"""Input service launched ONLY inside Studio's nested Gamescope display."""

import argparse
import hmac
import json
import os
import re
import socketserver
import subprocess
import threading
from dataclasses import asdict

from Xlib import X, display
from Xlib.ext import xtest

from .engine import MODIFIER_KEYS
from .isolated import MAX_MESSAGE
from .models import KEY_CODES, Step
from .x11 import BUTTON_MAP, WindowInfo, identity, window_title


def validate_environment(host_display):
    current = os.environ.get("DISPLAY", "")
    if (
        not re.fullmatch(r":\d+(?:\.\d+)?", current)
        or current.split(".")[0] == host_display.split(".")[0]
        or os.environ.get("XDG_CURRENT_DESKTOP", "").lower() != "gamescope"
        or not os.environ.get("GAMESCOPE_WAYLAND_DISPLAY")
    ):
        raise RuntimeError("Refusing input: the worker is not inside a separate Gamescope display")


class GameInput:
    def __init__(self, connection):
        self.connection = connection
        if not connection.has_extension("XTEST"):
            raise RuntimeError("The game display does not provide XTEST input")
        self.target = None
        self.held = set()
        self.errors = []
        connection.set_error_handler(lambda error, request: self.errors.append(str(error)))

    def windows(self):
        root = self.connection.screen().root
        prop = root.get_full_property(
            self.connection.intern_atom("_NET_CLIENT_LIST"), X.AnyPropertyType
        )
        ids = list(prop.value) if prop is not None else [w.id for w in root.query_tree().children]
        result = []
        for wid in ids[:200]:
            try:
                window = self.connection.create_resource_object("window", int(wid))
                title = window_title(self.connection, window)
                if title and window.get_attributes().map_state == X.IsViewable:
                    pid, wm_class = identity(self.connection, window)
                    result.append(asdict(WindowInfo(int(wid), str(title)[:256], pid, wm_class)))
            except Exception:
                continue
        return result

    def check(self):
        if self.target is None:
            raise RuntimeError("Select a game window inside this session")
        if identity(self.connection, self.window) != (self.target.pid, self.target.wm_class):
            raise RuntimeError("The isolated game window changed; select it again")
        if self.window.get_attributes().map_state != X.IsViewable:
            raise RuntimeError("The game window is no longer mapped in its session")
        # Only this private display's focus is changed, never the host desktop.
        focus = self.connection.get_input_focus().focus
        current = focus
        inside = False
        for _ in range(32):
            if getattr(current, "id", None) == self.window.id:
                inside = True
                break
            if not hasattr(current, "query_tree"):
                break
            tree = current.query_tree()
            if tree.parent.id == current.id or tree.parent.id == tree.root.id:
                break
            current = tree.parent
        if not inside:
            self.window.set_input_focus(X.RevertToParent, X.CurrentTime)
        self.connection.sync()
        if self.errors:
            raise RuntimeError(self.errors.pop(0))

    def point(self, point):
        if not isinstance(point, list) or len(point) != 2 or any(type(v) is not int for v in point):
            raise ValueError("Point must contain whole-number X and Y")
        self.check()
        geometry = self.window.get_geometry()
        if not 0 <= point[0] < geometry.width or not 0 <= point[1] < geometry.height:
            raise ValueError("Starting point is outside the game window")
        return self.connection.screen().root.translate_coords(self.window, *point)

    def dispatch(self, message):
        operation = message.get("op")
        if operation == "windows":
            return self.windows()
        if operation == "bind":
            target = message["target"]
            self.target = WindowInfo(**{**target, "wm_class": tuple(target["wm_class"])})
            self.window = self.connection.create_resource_object("window", self.target.id)
            self.check()
            self.connection.change_pointer_control(accel=(1, 1), threshold=0)
        elif operation == "check":
            self.check()
        elif operation in ("validate_point", "position"):
            point = self.point(message["point"])
            if operation == "position":
                xtest.fake_input(self.connection, X.MotionNotify, x=point.x, y=point.y)
                self.connection.sync()
                actual = self.connection.screen().root.query_pointer()
                if (actual.root_x, actual.root_y) != (point.x, point.y):
                    raise RuntimeError(
                        "The game constrained its cursor; the starting point could not be reached. Release pointer capture or disable coordinate reset."
                    )
        elif operation == "send":
            self.send(Step.from_dict(message["step"]))
        elif operation == "release":
            self.release()
        else:
            raise ValueError("Unknown game session operation")
        self.connection.sync()
        if self.errors:
            raise RuntimeError(self.errors.pop(0))

    def send(self, step):
        if self.target is None:
            raise RuntimeError("No game window selected")
        if step.action.startswith("key_"):
            down = step.action == "key_down"
            if down:
                self.held.add(step.code)
            else:
                self.held.discard(step.code)
            mouse = step.code.startswith("BTN_")
            code = BUTTON_MAP.get(step.code) if mouse else KEY_CODES[step.code] + 8
            if code is None or not mouse and not 8 <= code <= 255:
                raise ValueError("Unsupported input in this game display")
            kind = (
                (X.ButtonPress if down else X.ButtonRelease)
                if mouse
                else (X.KeyPress if down else X.KeyRelease)
            )
            xtest.fake_input(self.connection, kind, code)
        elif step.action == "move":
            xtest.fake_input(self.connection, X.MotionNotify, detail=1, x=step.x, y=step.y)
        elif step.action == "scroll":
            for value, positive, negative in ((step.y, 4, 5), (step.x, 7, 6)):
                if abs(value) > 100:
                    raise ValueError("Scroll is limited to 100 notches per event")
                for _ in range(abs(value)):
                    code = positive if value > 0 else negative
                    xtest.fake_input(self.connection, X.ButtonPress, code)
                    xtest.fake_input(self.connection, X.ButtonRelease, code)

    def release(self):
        for code in sorted(self.held, key=lambda c: (c in MODIFIER_KEYS, c)):
            self.send(Step(0, "key_up", code))
        self.held.clear()
        self.connection.sync()


class InputHandler(socketserver.StreamRequestHandler):
    def handle(self):
        connection = None
        service = None
        try:
            while True:
                line = self.rfile.readline(MAX_MESSAGE + 1)
                if not line:
                    return
                if len(line) > MAX_MESSAGE or not line.endswith(b"\n"):
                    return
                try:
                    message = json.loads(line)
                    if not isinstance(message, dict) or not hmac.compare_digest(
                        str(message.get("nonce", "")), self.server.nonce
                    ):
                        raise RuntimeError("Invalid game session identity")
                    if connection is None:
                        connection = display.Display(getattr(self.server, "display_name", None))
                        service = GameInput(connection)
                    value = service.dispatch(message)
                    reply = {"ok": True, "value": value}
                except Exception as exc:
                    reply = {"ok": False, "error": str(exc)[:2000]}
                self.wfile.write(json.dumps(reply, allow_nan=False).encode() + b"\n")
                self.wfile.flush()
        finally:
            if connection is not None:
                try:
                    if service is not None:
                        service.release()
                finally:
                    connection.close()


class InputServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--host-display", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    validate_environment(args.host_display)
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not command:
        raise ValueError("No game command supplied")
    with InputServer(args.socket, InputHandler) as server:
        server.nonce = args.nonce
        os.chmod(args.socket, 0o600)
        game = subprocess.Popen(
            command,
            env={
                **os.environ,
                "SDL_VIDEODRIVER": "x11",
                "QT_QPA_PLATFORM": "xcb",
                "GDK_BACKEND": "x11",
            },
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            game.wait()
        finally:
            server.shutdown()
            os.unlink(args.socket)


if __name__ == "__main__":
    main()
