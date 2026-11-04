"""Linux physical device monitoring and uinput output. Never grabs devices."""

import errno
import fcntl
import os
import select
import struct
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

from evdev import InputDevice, UInput, ecodes, list_devices

from .engine import MODIFIER_KEYS
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
    identifier: str = ""
    keyboard: bool = False
    mouse: bool = False
    issue: str = ""


def device_identifier(device):
    info = getattr(device, "info", None)
    hardware = (
        f"{getattr(info, 'bustype', 0)}:{getattr(info, 'vendor', 0)}:{getattr(info, 'product', 0)}"
    )
    location = getattr(device, "uniq", "") or getattr(device, "phys", "") or device.path
    return f"{hardware}:{device.name}:{location}"


def inaccessible_device(path, issue):
    try:
        name = (Path("/sys/class/input") / Path(path).name / "device/name").read_text().strip()
    except OSError:
        name = Path(path).name
    return DeviceInfo(path, name, False, issue=issue)


def event_paths():
    # list_devices() hides inaccessible devices, so glob as well for diagnostics.
    return sorted(set(list_devices()) | {str(p) for p in Path("/dev/input").glob("event*")})


def devices():
    result = []
    for path in event_paths():
        device = None
        try:
            device = InputDevice(path)
            if device.name.startswith(("Moonlight Studio", "Moonlight HID")):
                continue
            caps = device.capabilities()
            keys = set(caps.get(ecodes.EV_KEY, []))
            keyboard = bool(keys.intersection((ecodes.KEY_A, ecodes.KEY_SPACE, ecodes.KEY_ENTER)))
            relative = set(caps.get(ecodes.EV_REL, []))
            mouse = bool(
                keys.intersection(KEY_CODES[b] for b in KEY_CODES if b.startswith("BTN_"))
                or relative.intersection(
                    (ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL, ecodes.REL_HWHEEL)
                )
            )
            if not keyboard and not mouse:
                continue
            issue = (
                "Buttons/wheel only; pointer movement is not supported"
                if mouse and not {ecodes.REL_X, ecodes.REL_Y}.intersection(relative)
                else ""
            )
            result.append(
                DeviceInfo(
                    path, device.name, True, device_identifier(device), keyboard, mouse, issue
                )
            )
        except PermissionError:
            result.append(inaccessible_device(path, "Permission needed"))
        except OSError as exc:
            if exc.errno not in (errno.ENOENT, errno.ENODEV):
                result.append(inaccessible_device(path, str(exc)))
        finally:
            if device is not None:
                device.close()
    return result


def diagnostics(found=None):
    found = devices() if found is None else found
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
        self._pending = None
        self.held = set()
        self.keyboard = self.mouse = self.motion = True

    def start(self, keyboard=True, mouse=True, motion=True, limit=MAX_STEPS, start_at=None):
        with self._lock:
            if type(limit) is not int or not len(KEY_CODES) + 1 < limit <= MAX_STEPS:
                raise ValueError("Not enough space for a recording; start a new workflow.")
            self._limit = limit
            self.steps, self.held = [], set()
            self._sources = set()
            self._pending = None
            self.keyboard, self.mouse, self.motion = keyboard, mouse, motion
            self._last = time.monotonic() if start_at is None else start_at
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
            if event.type == ecodes.EV_SYN:
                if event.code == ecodes.SYN_REPORT:
                    self._flush_motion()
                return
            motion_action = (
                "move"
                if event.type == ecodes.EV_REL and event.code in (ecodes.REL_X, ecodes.REL_Y)
                else "scroll"
                if event.type == ecodes.EV_REL
                and event.code in (ecodes.REL_WHEEL, ecodes.REL_HWHEEL)
                else None
            )
            if self._pending and (
                motion_action != self._pending[0].action or source != self._pending[2]
            ):
                self._flush_motion()
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
                if step.action in ("move", "scroll"):
                    if not self._pending and len(self.steps) >= self._limit - len(KEY_CODES) - 1:
                        raise RuntimeError("Recording limit reached; recording has been stopped")
                    if self._pending:
                        previous, stamp, origin = self._pending
                        try:
                            self._pending = (
                                replace(previous, x=previous.x + step.x, y=previous.y + step.y),
                                stamp,
                                origin,
                            )
                            return
                        except ValueError:
                            self._flush_motion()
                            step = replace(step, delay_ms=max(0, (now - self._last) * 1000))
                    self._pending = (step, now, source)
                    return
                # Keep room for final releases and a trailing wait.
                self._append(step, now)

    def _append(self, step, stamp):
        if len(self.steps) >= self._limit - len(KEY_CODES) - 1:
            raise RuntimeError("Recording limit reached; recording has been stopped")
        self.steps.append(step)
        self._last = stamp

    def _flush_motion(self):
        if self._pending:
            step, stamp, _ = self._pending
            self._pending = None
            self._append(step, stamp)

    def stop(self):
        with self._lock:
            if self.active:
                self._flush_motion()
                delay = max(0, min((time.monotonic() - self._last) * 1000, 3_600_000))
                self.steps.append(Step(delay, "wait"))
                self.steps.extend(
                    Step(0, "key_up", code)
                    for code in sorted(self.held, key=lambda c: (c in MODIFIER_KEYS, c))
                )
            self.active = False
            self.held.clear()
            return list(self.steps)

    def preview(self):
        with self._lock:
            recent = list(self.steps[-80:])
            if self._pending is not None:
                recent.append(self._pending[0])
            return len(self.steps) + (1 if self._pending else 0), recent, sorted(self.held)

    def count(self):
        with self._lock:
            return len(self.steps) + (1 if self._pending is not None else 0)


class DeviceMonitor:
    def __init__(self, paths, recorder, hotkey, error):
        self.paths, self.recorder = paths, recorder
        self.hotkey, self.error = hotkey, error
        self._stop = threading.Event()
        self._thread = None
        self._monotonic_fds = set()
        self._realtime_offset = time.monotonic() - time.time()

    def start(self):
        if self._thread and self._thread.is_alive():
            raise RuntimeError("Input monitor is already running")
        self._stop.clear()
        opened = self._open()
        self._thread = threading.Thread(target=self._run, args=(opened,), daemon=True)
        try:
            self._thread.start()
        except Exception:
            for device in opened:
                device.close()
            self._thread = None
            raise

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(1)
        return self._thread is None or not self._thread.is_alive()

    def _open(self):
        opened = []
        self._monotonic_fds.clear()
        self._realtime_offset = time.monotonic() - time.time()
        try:
            for path in self.paths:
                device = InputDevice(path)
                if device.name.startswith(("Moonlight Studio", "Moonlight HID")):
                    device.close()
                    continue
                opened.append(device)
                # EVIOCSCLOCKID = _IOW('E', 0xa0, int), Linux input.h.
                try:
                    fcntl.ioctl(device.fd, 0x400445A0, struct.pack("i", time.CLOCK_MONOTONIC))
                    self._monotonic_fds.add(device.fd)
                except (OSError, AttributeError):
                    pass
            if not opened:
                raise RuntimeError(
                    "No readable keyboard/mouse devices. Open Setup for permissions."
                )
            return opened
        except Exception:
            for device in opened:
                device.close()
            raise

    def read_ready(self, device):
        events = []
        # evdev's native read_many returns at most 64 events. Drain a ready
        # device before merging: a single read can leave older reports behind.
        while not self._stop.is_set():
            try:
                batch = list(device.read())
            except BlockingIOError:
                break
            if not batch:
                if not events:
                    raise RuntimeError("Input device closed. Refresh the device list to reconnect.")
                break
            events.extend(batch)
            if len(batch) < 64:
                break
            if len(events) >= 8192:
                raise RuntimeError("Input backlog is too large. Recording stopped; try again.")
        return events

    def _run(self, opened=None):
        opened = opened or []
        try:
            if not opened:
                opened = self._open()
            while not self._stop.is_set():
                try:
                    ready, _, _ = select.select(opened, [], [], 0.1)
                except InterruptedError:
                    continue
                # Read all ready devices before dispatch. Kernel timestamps preserve
                # mouse/keyboard ordering even when select returns the keyboard first.
                pending = []
                for device in ready:
                    batch = self.read_ready(device)
                    offset = (
                        0
                        if getattr(device, "fd", None) in self._monotonic_fds
                        else self._realtime_offset
                    )
                    for event in batch:
                        if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_DROPPED:
                            raise RuntimeError(
                                "Input events were dropped. Recording stopped; try again."
                            )
                        pending.append((event.timestamp() + offset, device.path, event))
                # Stable sorting retains event/report order within each device.
                pending.sort(key=lambda item: item[0])
                for occurred_at, source, event in pending:
                    if self._stop.is_set():
                        return
                    if event.type == ecodes.EV_KEY and event.code in HOTKEYS:
                        if event.value == 1:
                            self.hotkey(HOTKEYS[event.code])
                        continue
                    self.recorder.feed(event, source=source, occurred_at=occurred_at)
        except Exception as exc:
            self.error(str(exc))
        finally:
            for device in opened:
                device.close()


class UInputBackend:
    coordinate_space = "desktop"
    # Allow the desktop to register the newly created virtual device. The wait is
    # handled by Replay and remains cancellable even with a zero user countdown.
    startup_delay = 0.5

    def __init__(self, pointer_factory=None):
        self.pointer_factory = pointer_factory
        if not os.access("/dev/uinput", os.W_OK):
            raise RuntimeError(
                "Cannot write /dev/uinput. Open Setup for the Linux permissions guide."
            )
        caps = {
            ecodes.EV_KEY: sorted(set(KEY_CODES.values())),
            ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL, ecodes.REL_HWHEEL],
        }
        self.device = UInput(caps, name=VIRTUAL_NAME)
        self.pointer = None

    def prepare_start(self, point):
        from .pointer import desktop_pointer

        self.pointer = (self.pointer_factory or desktop_pointer)()
        self.pointer.validate(point)

    def begin_cycle(self, point):
        self.pointer.move(point)

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
        try:
            if self.pointer:
                self.pointer.close()
        finally:
            self.device.close()
