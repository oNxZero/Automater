"""Linux physical device monitoring and uinput output. Never grabs devices."""

import os
import select
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from evdev import InputDevice, UInput, ecodes, list_devices

from .models import KEY_CODES, MAX_STEPS, Step

VIRTUAL_NAME = "Moonlight Studio Virtual Input"
HOTKEYS = {
    ecodes.KEY_F6: "record",
    ecodes.KEY_F7: "play",
    ecodes.KEY_F8: "pause",
    ecodes.KEY_F12: "stop",
}
CODE_NAMES = {value: name for name, value in sorted(KEY_CODES.items(), reverse=True)}


@dataclass(frozen=True)
class DeviceInfo:
    path: str
    name: str
    readable: bool


def devices():
    result = []
    # list_devices() hides inaccessible devices, so glob as well for diagnostics.
    paths = set(list_devices()) | {str(p) for p in Path("/dev/input").glob("event*")}
    for path in sorted(paths):
        try:
            with InputDevice(path) as device:
                if device.name.startswith(("Moonlight Studio", "Moonlight HID")):
                    continue
                caps = device.capabilities()
                keys = set(caps.get(ecodes.EV_KEY, []))
                if not keys.intersection(KEY_CODES.values()) and ecodes.EV_REL not in caps:
                    continue
                result.append(DeviceInfo(path, device.name, True))
        except OSError:
            result.append(DeviceInfo(path, Path(path).name + " (permission required)", False))
    return result


def diagnostics():
    found = devices()
    return {
        "session": os.environ.get("XDG_SESSION_TYPE", "unknown"),
        "uinput_exists": Path("/dev/uinput").exists(),
        "uinput_writable": os.access("/dev/uinput", os.W_OK),
        "readable_devices": sum(d.readable for d in found),
        "devices": [d.__dict__ for d in found],
        "display": bool(os.environ.get("DISPLAY")),
    }


class Recorder:
    def __init__(self):
        self._lock = threading.Lock()
        self.active = False
        self.steps = []
        self.held = set()
        self.keyboard = self.mouse = self.motion = True

    def start(self, keyboard=True, mouse=True, motion=True):
        with self._lock:
            self.steps, self.held = [], set()
            self._sources = set()
            self.keyboard, self.mouse, self.motion = keyboard, mouse, motion
            self._last = time.monotonic()
            self._started = self._last
            self.active = True

    def feed(self, event, source=None, occurred_at=None):
        with self._lock:
            if not self.active:
                return
            now = time.monotonic() if occurred_at is None else occurred_at
            # Discard events that were queued before recording started.
            if now < self._started:
                return
            now = max(self._last, now)
            delay = min((now - self._last) * 1000, 3_600_000)
            step = None
            if event.type == ecodes.EV_KEY and event.code in CODE_NAMES:
                if event.code in HOTKEYS or event.value not in (0, 1):
                    return
                code = CODE_NAMES[event.code]
                if not (self.mouse if code.startswith("BTN_") else self.keyboard):
                    return
                if event.value == 1:
                    if (source, code) in self._sources:
                        return
                    self._sources.add((source, code))
                    if code in self.held:
                        return
                    self.held.add(code)
                else:
                    if (source, code) not in self._sources:
                        return
                    self._sources.remove((source, code))
                    if any(held_code == code for _, held_code in self._sources):
                        return
                    self.held.remove(code)
                step = Step(delay, "key_down" if event.value else "key_up", code)
            elif event.type == ecodes.EV_REL:
                if event.code in (ecodes.REL_X, ecodes.REL_Y) and self.motion:
                    step = Step(
                        delay,
                        "move",
                        x=event.value if event.code == ecodes.REL_X else 0,
                        y=event.value if event.code == ecodes.REL_Y else 0,
                    )
                elif event.code in (ecodes.REL_WHEEL, ecodes.REL_HWHEEL) and self.mouse:
                    step = Step(
                        delay,
                        "scroll",
                        x=event.value if event.code == ecodes.REL_HWHEEL else 0,
                        y=event.value if event.code == ecodes.REL_WHEEL else 0,
                    )
            if step:
                # Keep room for final releases and a trailing wait.
                if len(self.steps) >= MAX_STEPS - len(KEY_CODES) - 1:
                    raise RuntimeError("Recording limit reached; recording has been stopped")
                self.steps.append(step)
                self._last = now

    def stop(self):
        with self._lock:
            if self.active:
                delay = max(0, min((time.monotonic() - self._last) * 1000, 3_600_000))
                self.steps.append(Step(delay, "wait"))
                self.steps.extend(Step(0, "key_up", code) for code in sorted(self.held))
            self.active = False
            self.held.clear()
            return list(self.steps)

    def count(self):
        with self._lock:
            return len(self.steps)


class DeviceMonitor:
    def __init__(self, paths, recorder, hotkey, error):
        self.paths, self.recorder = paths, recorder
        self.hotkey, self.error = hotkey, error
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(1)

    def _run(self):
        opened = []
        try:
            for path in self.paths:
                device = InputDevice(path)
                if device.name.startswith(("Moonlight Studio", "Moonlight HID")):
                    device.close()
                    continue
                opened.append(device)
            if not opened:
                raise RuntimeError(
                    "No readable keyboard/mouse devices. Open Setup for permissions."
                )
            while not self._stop.is_set():
                ready, _, _ = select.select(opened, [], [], 0.1)
                for device in ready:
                    for event in device.read():
                        if self._stop.is_set():
                            return
                        if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_DROPPED:
                            raise RuntimeError(
                                "Input events were dropped. Recording stopped; try again."
                            )
                        if event.type == ecodes.EV_KEY and event.code in HOTKEYS:
                            if event.value == 1:
                                self.hotkey(HOTKEYS[event.code])
                            continue
                        self.recorder.feed(
                            event,
                            source=device.path,
                            occurred_at=time.monotonic() + (event.timestamp() - time.time()),
                        )
        except Exception as exc:
            self.error(str(exc))
        finally:
            for device in opened:
                device.close()


class UInputBackend:
    def __init__(self):
        if not os.access("/dev/uinput", os.W_OK):
            raise RuntimeError(
                "Cannot write /dev/uinput. Open Setup for the Linux permissions guide."
            )
        caps = {
            ecodes.EV_KEY: sorted(set(KEY_CODES.values())),
            ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL, ecodes.REL_HWHEEL],
        }
        self.device = UInput(caps, name=VIRTUAL_NAME)

    def check(self):
        pass

    def send(self, step):
        if step.action.startswith("key_"):
            self.device.write(ecodes.EV_KEY, KEY_CODES[step.code], int(step.action == "key_down"))
        elif step.action in ("move", "scroll"):
            codes = (
                (ecodes.REL_X, ecodes.REL_Y)
                if step.action == "move"
                else (ecodes.REL_HWHEEL, ecodes.REL_WHEEL)
            )
            for code, value in zip(codes, (step.x, step.y)):
                if value:
                    self.device.write(ecodes.EV_REL, code, value)
        self.device.syn()

    def close(self):
        self.device.close()
