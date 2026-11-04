"""Best-effort background delivery to one X11 client; never changes real focus."""

from dataclasses import dataclass

from Xlib import X, display, protocol

from .models import KEY_CODES

BUTTON_MAP = {
    "BTN_LEFT": 1,
    "BTN_MIDDLE": 2,
    "BTN_RIGHT": 3,
    "BTN_SIDE": 8,
    "BTN_EXTRA": 9,
    "BTN_BACK": 8,
    "BTN_FORWARD": 9,
}
MODIFIERS = {
    "KEY_LEFTSHIFT": X.ShiftMask,
    "KEY_RIGHTSHIFT": X.ShiftMask,
    "KEY_LEFTCTRL": X.ControlMask,
    "KEY_RIGHTCTRL": X.ControlMask,
    "KEY_LEFTALT": X.Mod1Mask,
    "KEY_RIGHTALT": X.Mod5Mask,
    "KEY_LEFTMETA": X.Mod4Mask,
    "KEY_RIGHTMETA": X.Mod4Mask,
}


@dataclass(frozen=True)
class WindowInfo:
    id: int
    title: str
    pid: int
    wm_class: tuple


def identity(connection, window):
    prop = window.get_full_property(connection.intern_atom("_NET_WM_PID"), X.AnyPropertyType)
    return (
        int(prop.value[0]) if prop is not None and len(prop.value) else 0,
        tuple(window.get_wm_class() or ()),
    )


def window_title(connection, window):
    name = window.get_full_property(
        connection.intern_atom("_NET_WM_NAME"), connection.intern_atom("UTF8_STRING")
    )
    return name.value.decode("utf-8", "replace") if name is not None else window.get_wm_name()


def windows():
    connection = display.Display()
    try:
        root = connection.screen().root
        prop = root.get_full_property(connection.intern_atom("_NET_CLIENT_LIST"), X.AnyPropertyType)
        candidates = (
            list(prop.value) if prop is not None else [w.id for w in root.query_tree().children]
        )
        result = []
        for wid in candidates:
            try:
                window = connection.create_resource_object("window", int(wid))
                title = window_title(connection, window)
                if title:
                    pid, wm_class = identity(connection, window)
                    result.append(WindowInfo(int(wid), title, pid, wm_class))
            except Exception:
                continue  # Windows can close during enumeration.
        return sorted(result, key=lambda w: w.title.lower())
    finally:
        connection.close()


class BackgroundBackend:
    coordinate_space = "window"

    def __init__(self, target):
        self.connection = display.Display()
        self.target = target
        self.window = self.connection.create_resource_object("window", target.id)
        self.state = 0
        self.modifiers = set()
        self.errors = []
        self.connection.set_error_handler(lambda err, request: self.errors.append(str(err)))
        try:
            self.check()
            geometry = self.window.get_geometry()
            self.width, self.height = geometry.width, geometry.height
            self.x, self.y = self.width // 2, self.height // 2
        except Exception:
            self.connection.close()
            raise

    def check(self):
        try:
            if identity(self.connection, self.window) != (self.target.pid, self.target.wm_class):
                raise RuntimeError("Target window identity changed; select it again")
            self.window.get_attributes()
            self.connection.sync()
            if self.errors:
                raise RuntimeError(self.errors.pop(0))
        except Exception as exc:
            raise RuntimeError(f"Target window is unavailable: {exc}") from exc

    def prepare(self, steps):
        for step in steps:
            if not step.enabled:
                continue
            if step.action.startswith("key_"):
                if step.code.startswith("BTN_"):
                    if step.code not in BUTTON_MAP:
                        raise ValueError(f"{step.code} is unsupported in background mode")
                elif not 8 <= KEY_CODES[step.code] + 8 <= 255:
                    raise ValueError(f"{step.code} cannot be mapped to an X11 keycode")
            if step.action == "scroll" and max(abs(step.x), abs(step.y)) > 100:
                raise ValueError("Background scroll is limited to 100 notches per step")

    def prepare_start(self, point):
        self.check()
        geometry = self.window.get_geometry()
        self.width, self.height = geometry.width, geometry.height
        if not 0 <= point[0] < self.width or not 0 <= point[1] < self.height:
            raise ValueError("Starting point must be inside the target window's client area")

    def begin_cycle(self, point):
        self.prepare_start(point)
        self.x, self.y = point
        self._event(protocol.event.MotionNotify, X.NotifyNormal, X.PointerMotionMask)
        self.connection.sync()

    def _event(self, cls, detail, mask):
        root = self.connection.screen().root
        position = root.translate_coords(self.window, self.x, self.y)
        event = cls(
            time=X.CurrentTime,
            root=root,
            window=self.window,
            child=X.NONE,
            root_x=position.x,
            root_y=position.y,
            event_x=self.x,
            event_y=self.y,
            state=self.state,
            same_screen=1,
            detail=detail,
        )
        self.window.send_event(event, event_mask=mask, propagate=False)

    def _button(self, button, down):
        self._event(
            protocol.event.ButtonPress if down else protocol.event.ButtonRelease,
            button,
            X.ButtonPressMask if down else X.ButtonReleaseMask,
        )
        bit = {1: X.Button1Mask, 2: X.Button2Mask, 3: X.Button3Mask}.get(button, 0)
        self.state = self.state | bit if down else self.state & ~bit

    def send(self, step):
        if step.action.startswith("key_"):
            down = step.action == "key_down"
            buttons = BUTTON_MAP
            if step.code.startswith("BTN_"):
                if step.code not in buttons:
                    raise ValueError(f"{step.code} is unsupported in background mode")
                self._button(buttons[step.code], down)
            else:
                # Xorg/Xwayland's standard evdev XKB mapping: Linux code + 8.
                keycode = KEY_CODES[step.code] + 8
                if not 8 <= keycode <= 255:
                    raise ValueError(f"{step.code} cannot be mapped to an X11 keycode")
                self._event(
                    protocol.event.KeyPress if down else protocol.event.KeyRelease,
                    keycode,
                    X.KeyPressMask if down else X.KeyReleaseMask,
                )
                if step.code in MODIFIERS:
                    if down:
                        self.modifiers.add(step.code)
                    else:
                        self.modifiers.discard(step.code)
                    mask = 0
                    for code in self.modifiers:
                        mask |= MODIFIERS[code]
                    self.state = (
                        self.state
                        & ~(X.ShiftMask | X.ControlMask | X.Mod1Mask | X.Mod4Mask | X.Mod5Mask)
                    ) | mask
        elif step.action == "move":
            self.x = max(0, min(self.width - 1, self.x + step.x))
            self.y = max(0, min(self.height - 1, self.y + step.y))
            self._event(protocol.event.MotionNotify, X.NotifyNormal, X.PointerMotionMask)
        elif step.action == "scroll":
            for value, positive, negative in ((step.y, 4, 5), (step.x, 7, 6)):
                if abs(value) > 100:
                    raise ValueError("Background scroll is limited to 100 notches per step")
                for _ in range(abs(value)):
                    button = positive if value > 0 else negative
                    self._button(button, True)
                    self._button(button, False)
        self.connection.sync()
        if self.errors:
            raise RuntimeError(self.errors.pop(0))

    def close(self):
        self.connection.close()


class FocusGuard:
    """Use actual X input focus, including child widgets; no focus/activation requests."""

    def __init__(self, target):
        self.target = target
        self.connection = display.Display()

    def check(self):
        target = self.connection.create_resource_object("window", self.target.id)
        if identity(self.connection, target) != (self.target.pid, self.target.wm_class):
            raise RuntimeError("Selected window closed or its identity changed")
        focus = self.connection.get_input_focus().focus
        seen = set()
        while hasattr(focus, "id") and focus.id not in seen:
            if focus.id == target.id:
                return
            seen.add(focus.id)
            if focus.id == self.connection.screen().root.id:
                break
            focus = focus.query_tree().parent
        raise RuntimeError(
            "Selected window lost focus. Focus it during the countdown and keep it active."
        )

    def close(self):
        self.connection.close()
