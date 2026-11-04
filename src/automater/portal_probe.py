"""Read portal capabilities without creating a session or opening permission UI."""

import asyncio

from dbus_next import Message, MessageType
from dbus_next.aio import MessageBus

SERVICE = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
REMOTE = "org.freedesktop.portal.RemoteDesktop"
SCREENCAST = "org.freedesktop.portal.ScreenCast"


async def read_capabilities(bus):
    result = {}
    for interface, field in ((REMOTE, "remote_desktop"), (SCREENCAST, "screen_cast")):
        reply = await bus.call(
            Message(
                destination=SERVICE,
                path=PATH,
                interface="org.freedesktop.DBus.Properties",
                member="GetAll",
                signature="s",
                body=[interface],
            )
        )
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(
                "This desktop's portal does not expose "
                + interface.rsplit(".", 1)[-1]
                + ". Install/configure a backend supporting RemoteDesktop and ScreenCast; relative replay still works with uinput."
            )
        result[field] = {key: value.value for key, value in reply.body[0].items()}
    remote, screen = result["remote_desktop"], result["screen_cast"]
    result["pointer_supported"] = bool(remote.get("AvailableDeviceTypes", 0) & 2)
    result["monitors_supported"] = bool(screen.get("AvailableSourceTypes", 0) & 1)
    return result


async def probe_async(bus_address=None):
    bus = None
    try:
        bus = await MessageBus(bus_address=bus_address).connect()
        result = await read_capabilities(bus)
        result["available"] = result["pointer_supported"] and result["monitors_supported"]
        result["message"] = (
            "Pointer/monitor portal interfaces are available; Connect still requires your approval."
            if result["available"]
            else "Portal is present but does not offer pointer control and physical monitors."
        )
        return result
    finally:
        if bus:
            bus.disconnect()


def probe(bus_address=None, timeout=3):
    try:
        return asyncio.run(asyncio.wait_for(probe_async(bus_address), timeout))
    except Exception as exc:
        return {
            "available": False,
            "message": str(exc) or "Portal check timed out; no permission was requested.",
        }
