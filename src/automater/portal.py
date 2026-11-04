"""User-authorized Wayland absolute positioning through XDG Desktop Portal.

The bus has its own asyncio thread. Qt stays responsive during permission dialogs;
replay waits only for individual input calls. No screen frames are opened or saved.
"""

import asyncio
import threading
import uuid

from dbus_next import Message, MessageType, Variant
from dbus_next.aio import MessageBus
from PySide6.QtCore import QObject, Signal

from .portal_probe import read_capabilities

SERVICE = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
REMOTE = "org.freedesktop.portal.RemoteDesktop"
SCREENCAST = "org.freedesktop.portal.ScreenCast"


def unpack(value):
    if isinstance(value, Variant):
        return unpack(value.value)
    if isinstance(value, dict):
        return {k: unpack(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [unpack(v) for v in value]
    return value


class PortalConnection(QObject):
    ready = Signal()
    failed = Signal(str)
    revoked = Signal()

    def __init__(self, parent=None, bus_address=None):
        super().__init__(parent)
        self.bus_address = bus_address
        self.active = False
        self.session = None
        self.streams = []
        self.bus = self.loop = self.thread = None
        self.pending = {}
        self.requests_to_close = set()
        self.cancelled = threading.Event()
        self.closing = False

    def connect_pointer(self):
        if self.thread and self.thread.is_alive():
            return
        self.cancelled.clear()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.authorization_task = self.loop.create_task(self.authorize())
        try:
            self.loop.run_forever()
        finally:
            self.closing = True
            self.active = False
            tasks = asyncio.all_tasks(self.loop)
            for pending_task in tasks:
                pending_task.cancel()
            self.loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            if self.bus:
                for path in self.requests_to_close:
                    try:
                        self.loop.run_until_complete(
                            asyncio.wait_for(
                                self.call("Close", "", [], "org.freedesktop.portal.Request", path),
                                1,
                            )
                        )
                    except Exception:
                        pass
                if self.session:
                    try:
                        self.loop.run_until_complete(
                            asyncio.wait_for(
                                self.call(
                                    "Close", "", [], "org.freedesktop.portal.Session", self.session
                                ),
                                1,
                            )
                        )
                    except Exception:
                        pass
                self.bus.disconnect()
            self.loop.close()

    async def call(self, member, signature, body, interface=REMOTE, path=PATH):
        reply = await self.bus.call(
            Message(
                destination=SERVICE,
                path=path,
                interface=interface,
                member=member,
                signature=signature,
                body=body,
            )
        )
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(f"Desktop pointer control: {reply.error_name}: {reply.body}")
        return reply

    def response(self, message):
        if message.message_type != MessageType.SIGNAL:
            return
        if message.interface == "org.freedesktop.portal.Request" and message.member == "Response":
            future = self.pending.get(message.path)
            if future is not None and not future.done():
                future.set_result(message.body)
        elif (
            message.interface == "org.freedesktop.portal.Session"
            and message.member == "Closed"
            and message.path == self.session
        ):
            if self.closing or self.cancelled.is_set():
                return
            self.active = False
            self.revoked.emit()
            self.loop.stop()

    async def request(self, member, signature, body, options, interface=REMOTE):
        token = "automater_" + uuid.uuid4().hex
        sender = self.bus.unique_name[1:].replace(".", "_")
        path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        options = {**options, "handle_token": Variant("s", token)}
        future = self.loop.create_future()
        self.pending[path] = future
        try:
            reply = await asyncio.wait_for(
                self.call(member, signature, [*body, options], interface), 10
            )
            if reply.body[0] != path:
                raise RuntimeError("Desktop portal returned an unexpected request handle")
            code, results = await asyncio.wait_for(future, 120)
            if code != 0:
                raise RuntimeError(
                    "Pointer permission was cancelled or denied. Existing workflow is unchanged."
                )
            return unpack(results)
        finally:
            if not future.done() or future.cancelled():
                self.requests_to_close.add(path)
            self.pending.pop(path, None)

    async def authorize(self):
        try:
            if self.cancelled.is_set():
                self.loop.stop()
                return
            self.bus = await MessageBus(bus_address=self.bus_address).connect()
            support = await asyncio.wait_for(read_capabilities(self.bus), 3)
            if not support["pointer_supported"] or not support["monitors_supported"]:
                raise RuntimeError(
                    "This portal cannot control the pointer on physical monitors. Relative replay still works with reset disabled."
                )
            self.bus.add_message_handler(self.response)
            for interface in ("org.freedesktop.portal.Request", "org.freedesktop.portal.Session"):
                reply = await self.bus.call(
                    Message(
                        destination="org.freedesktop.DBus",
                        path="/org/freedesktop/DBus",
                        interface="org.freedesktop.DBus",
                        member="AddMatch",
                        signature="s",
                        body=[f"type='signal',sender='{SERVICE}',interface='{interface}'"],
                    )
                )
                if reply.message_type == MessageType.ERROR:
                    raise RuntimeError(
                        "Could not subscribe to desktop pointer permission responses"
                    )
            created = await self.request(
                "CreateSession",
                "a{sv}",
                [],
                {"session_handle_token": Variant("s", "automater_" + uuid.uuid4().hex)},
            )
            self.session = created["session_handle"]
            await self.request(
                "SelectDevices", "oa{sv}", [self.session], {"types": Variant("u", 2)}
            )
            await self.request(
                "SelectSources",
                "oa{sv}",
                [self.session],
                {"types": Variant("u", 1), "multiple": Variant("b", True)},
                SCREENCAST,
            )
            result = await self.request("Start", "osa{sv}", [self.session, ""], {})
            if not result.get("devices", 0) & 2:
                raise RuntimeError("Desktop did not grant pointer control")
            self.streams = result.get("streams", [])
            if not self.streams or any(
                "position" not in props
                or "size" not in props
                or len(props["position"]) != 2
                or len(props["size"]) != 2
                or min(props["size"]) <= 0
                for _, props in self.streams
            ):
                raise RuntimeError(
                    "Desktop did not provide monitor coordinates. Select physical monitors, not windows."
                )
            if self.cancelled.is_set():
                self.loop.stop()
                return
            self.active = True
            self.loop.create_task(self.watch_disconnect())
            self.ready.emit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.failed.emit(str(exc))
            self.loop.stop()

    async def watch_disconnect(self):
        try:
            await self.bus.wait_for_disconnect()
        except Exception:
            pass
        if self.active and not self.cancelled.is_set():
            self.active = False
            self.revoked.emit()
            self.loop.stop()

    def locate(self, point):
        if not self.active:
            raise RuntimeError(
                "Connect Wayland pointer control in Settings → Start before using coordinate reset"
            )
        for stream, props in self.streams:
            x, y = props["position"]
            width, height = props["size"]
            if x <= point[0] < x + width and y <= point[1] < y + height:
                logical = props.get("logical_size", (width, height))
                return (
                    stream,
                    float(point[0] - x) * logical[0] / width,
                    float(point[1] - y) * logical[1] / height,
                )
        raise ValueError("Starting point is outside the monitors approved for pointer control")

    async def send_position(self, point):
        stream, x, y = self.locate(point)
        await self.call(
            "NotifyPointerMotionAbsolute", "oa{sv}udd", [self.session, {}, stream, x, y]
        )

    def move(self, point):
        self.locate(point)
        future = asyncio.run_coroutine_threadsafe(self.send_position(point), self.loop)
        try:
            future.result(timeout=2)
        except Exception as exc:
            future.cancel()
            raise RuntimeError(f"Desktop pointer movement failed: {exc}") from exc

    def close(self):
        self.cancelled.set()
        self.active = False
        if self.loop and self.loop.is_running():
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except RuntimeError:
                pass


class PortalPointer:
    def __init__(self, connection):
        self.connection = connection

    def validate(self, point):
        self.connection.locate(point)

    def move(self, point):
        self.connection.move(point)

    def close(self):
        pass  # Session belongs to the window and is reusable across replay runs.
