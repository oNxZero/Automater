"""KDE window discovery and explicit playback activation; no persistent KWin settings."""

import asyncio
import json
import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from dbus_next import Message, MessageType
from dbus_next.aio import MessageBus
from PySide6.QtCore import QObject, Signal

KWIN = "org.kde.KWin"
SCRIPTING = "org.kde.kwin.Scripting"
CALLBACK = "io.github.onxzero.Automater.Windows"


@dataclass(frozen=True)
class DesktopWindow:
    id: str
    title: str
    pid: int
    wm_class: tuple


def observer_script(service):
    # Only reads window properties. The callback destination is a generated bus name.
    return """
function snapshot() {
    const active = workspace.activeWindow;
    const windows = workspace.windowList().filter(w => !w.deleted && !w.specialWindow);
    callDBus(SERVICE, "/Windows", "io.github.onxzero.Automater.Windows", "Snapshot",
        JSON.stringify({active: active ? String(active.internalId) : "",
          windows: windows.map(w => ({id: String(w.internalId), title: w.caption,
            pid: w.pid, app: String(w.resourceClass)}))}));
}
workspace.windowAdded.connect(function(w) {
    w.captionChanged.connect(snapshot);
    snapshot();
});
workspace.windowList().forEach(w => w.captionChanged.connect(snapshot));
workspace.windowRemoved.connect(snapshot);
workspace.windowActivated.connect(snapshot);
workspace.currentDesktopChanged.connect(snapshot);
snapshot();
""".replace("SERVICE", json.dumps(service))


def activation_script(target):
    return f"""
const w = workspace.windowList().find(w => String(w.internalId) === {json.dumps(target.id)} && w.pid === {target.pid} && String(w.resourceClass) === {json.dumps(target.wm_class[0])});
if (!w) throw new Error("Selected window closed");
w.minimized = false;
if (w.desktops && w.desktops.length) workspace.currentDesktop = w.desktops[0];
workspace.activeWindow = w;
"""


class WindowObserver(QObject):
    changed = Signal()

    def __init__(self, parent=None, bus_address=None):
        super().__init__(parent)
        self.bus_address = bus_address
        self.lock = threading.Lock()
        self.windows = []
        self.active_id = ""
        self.available = False
        self.error = ""
        self.thread = self.loop = self.stop_event = None
        self._call = None
        self.closing = threading.Event()

    def emit_changed(self):
        try:
            self.changed.emit()
        except RuntimeError:
            pass  # The owner can be destroyed while D-Bus cleanup finishes.

    def snapshot(self):
        with self.lock:
            return list(self.windows), self.active_id, self.available, self.error

    def check_focus(self, target):
        windows, active, available, _ = self.snapshot()
        if not available:
            raise RuntimeError("Window tracking disconnected. Select your window again.")
        if not any(
            (w.id, w.pid, w.wm_class) == (target.id, target.pid, target.wm_class) for w in windows
        ):
            raise RuntimeError("The selected window closed. Select an open window again.")
        if active != target.id:
            raise RuntimeError(
                "Selected window lost focus. Focus it during the countdown and keep it active."
            )

    def activate(self, target):
        windows, active, available, _ = self.snapshot()
        if not available or self.loop is None or self._call is None:
            raise RuntimeError(
                "Window tracking is unavailable. Refresh the window picker, or choose Any active window for desktop playback."
            )
        if not any(
            (w.id, w.pid, w.wm_class) == (target.id, target.pid, target.wm_class) for w in windows
        ):
            raise RuntimeError("The selected window closed. Choose an open window again.")
        if active == target.id:
            return
        future = asyncio.run_coroutine_threadsafe(self._activate(target), self.loop)
        try:
            future.result(timeout=2)
        except TimeoutError as exc:
            future.cancel()
            raise RuntimeError(
                "The desktop could not activate this app. Focus it manually and try again."
            ) from exc
        except Exception as exc:
            future.cancel()
            raise RuntimeError(
                str(exc) or "Window activation was cancelled or disconnected."
            ) from exc

    async def _activate(self, target):
        name = "automater_activate_" + uuid.uuid4().hex
        path, loaded = None, False
        script = activation_script(target)
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".js", prefix="automater-activate-", delete=False
            ) as file:
                path = Path(file.name)
                file.write(script)
            script_id = (
                await self._call("/Scripting", SCRIPTING, "loadScript", "ss", [str(path), name])
            )[0]
            if script_id < 0:
                raise RuntimeError("The desktop refused to activate the selected window")
            loaded = True
            await self._call(f"/Scripting/Script{script_id}", "org.kde.kwin.Script", "run")
            deadline = time.monotonic() + 0.75
            while self.snapshot()[1] != target.id and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            self.check_focus(target)
        finally:
            if loaded:
                try:
                    await self._call("/Scripting", SCRIPTING, "unloadScript", "s", [name])
                except Exception:
                    pass
            if path:
                path.unlink(missing_ok=True)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.closing.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        asyncio.run(self._observe())

    async def _observe(self):
        self.loop = asyncio.get_running_loop()
        self.stop_event = asyncio.Event()
        bus = None
        loaded = False
        name = "automater_windows_" + uuid.uuid4().hex
        service = "io.github.onxzero.Automater.Windows.s" + uuid.uuid4().hex
        path = None
        try:
            bus = await MessageBus(bus_address=self.bus_address).connect()

            async def call(path, interface, member, signature="", body=None, destination=KWIN):
                reply = await asyncio.wait_for(
                    bus.call(
                        Message(
                            destination=destination,
                            path=path,
                            interface=interface,
                            member=member,
                            signature=signature,
                            body=body or [],
                        )
                    ),
                    3,
                )
                if reply.message_type == MessageType.ERROR:
                    raise RuntimeError(str(reply.body[0]) if reply.body else reply.error_name)
                return reply.body

            self._call = call
            owner = (
                await call(
                    "/org/freedesktop/DBus",
                    "org.freedesktop.DBus",
                    "GetNameOwner",
                    "s",
                    [KWIN],
                    "org.freedesktop.DBus",
                )
            )[0]
            await bus.request_name(service)
            ready = asyncio.Event()

            def handle(message):
                if (
                    message.message_type == MessageType.METHOD_CALL
                    and message.path == "/Windows"
                    and message.interface == CALLBACK
                    and message.member == "Snapshot"
                    and message.sender == owner
                ):
                    try:
                        data = json.loads(message.body[0])
                        windows = [
                            DesktopWindow(w["id"], w["title"], w["pid"], (w["app"],))
                            for w in data["windows"]
                            if w["title"]
                        ]
                        with self.lock:
                            self.windows, self.active_id = windows, data["active"]
                            self.available, self.error = True, ""
                        ready.set()
                        self.emit_changed()
                        bus.send(Message.new_method_return(message))
                    except (KeyError, TypeError, ValueError) as exc:
                        bus.send(Message.new_error(message, CALLBACK + ".Invalid", str(exc)))
                    return True
                if (
                    message.message_type == MessageType.SIGNAL
                    and message.interface == "org.freedesktop.DBus"
                    and message.member == "NameOwnerChanged"
                    and message.body[0] == KWIN
                    and message.body[2] != owner
                ):
                    self.stop_event.set()

            bus.add_message_handler(handle)
            await call(
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "AddMatch",
                "s",
                [
                    "type='signal',interface='org.freedesktop.DBus',member='NameOwnerChanged',arg0='org.kde.KWin'"
                ],
                "org.freedesktop.DBus",
            )
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".js", prefix="automater-windows-", delete=False
            ) as file:
                path = Path(file.name)
                file.write(observer_script(service))
            script_id = (
                await call("/Scripting", SCRIPTING, "loadScript", "ss", [str(path), name])
            )[0]
            if script_id < 0:
                raise RuntimeError("KDE refused open-window discovery")
            loaded = True
            await call(f"/Scripting/Script{script_id}", "org.kde.kwin.Script", "run")
            await asyncio.wait_for(ready.wait(), 3)
            path.unlink(missing_ok=True)
            if not self.closing.is_set():
                stopped = asyncio.create_task(self.stop_event.wait())
                disconnected = asyncio.create_task(bus.wait_for_disconnect())
                try:
                    await asyncio.wait([stopped, disconnected], return_when=asyncio.FIRST_COMPLETED)
                finally:
                    stopped.cancel()
                    disconnected.cancel()
        except Exception as exc:
            with self.lock:
                self.error = str(exc) or "KDE window discovery is unavailable"
        finally:
            if loaded and bus and bus.connected:
                try:
                    await call("/Scripting", SCRIPTING, "unloadScript", "s", [name])
                except Exception:
                    pass
            if path:
                path.unlink(missing_ok=True)
            if bus:
                bus.disconnect()
            with self.lock:
                self.available = False
            self.emit_changed()

    def close(self):
        self.closing.set()
        if self.loop and self.stop_event:
            try:
                self.loop.call_soon_threadsafe(self.stop_event.set)
            except RuntimeError:
                pass


def discover_windows(x11_windows, observer):
    """Prefer KDE's complete list; retain unmatched X11 clients when available."""
    desktop, _, available, _ = observer.snapshot()
    if not available:
        return sorted(
            (w for w in x11_windows if w.pid != os.getpid()), key=lambda w: w.title.casefold()
        )
    result = [w for w in desktop if w.pid != os.getpid()]
    for window in x11_windows:
        if window.pid != os.getpid() and not any(
            w.pid == window.pid and w.title == window.title for w in result
        ):
            result.append(window)
    return sorted(result, key=lambda w: (w.title.casefold(), w.pid, str(w.id)))


def matching_x11(window, x11_windows):
    if not isinstance(window, DesktopWindow):
        return window
    matches = [w for w in x11_windows if w.pid == window.pid and w.title == window.title]
    return matches[0] if len(matches) == 1 else None


class GuardedDesktopBackend:
    """Focus checks do not block cleanup releases when the destination changes."""

    def __init__(self, backend, check_focus, close_guard=lambda: None, activate_window=None):
        self.backend = backend
        self.check_focus = check_focus
        self.close_guard = close_guard
        self.activate_window = activate_window

    def __getattr__(self, name):
        return getattr(self.backend, name)

    def activate(self):
        if self.activate_window is not None:
            self.activate_window()

    def check(self):
        self.check_focus()
        self.backend.check()

    def begin_cycle(self, point):
        self.check()
        self.backend.begin_cycle(point)

    def send(self, step):
        if step.action not in ("key_up", "wait"):
            self.check()
        self.backend.send(step)

    def close(self):
        try:
            self.backend.close()
        finally:
            self.close_guard()


def guarded_desktop(factory, target, observer, auto_activate=True):
    from .x11 import FocusGuard

    backend = factory()
    try:
        if isinstance(target, DesktopWindow):
            return GuardedDesktopBackend(
                backend,
                lambda: observer.check_focus(target),
                activate_window=(lambda: observer.activate(target)) if auto_activate else None,
            )
        guard = FocusGuard(target)
        return GuardedDesktopBackend(
            backend, guard.check, guard.close, guard.activate if auto_activate else None
        )
    except Exception:
        backend.close()
        raise
