"""Real D-Bus serialization against a private fake portal; never controls a desktop."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading

import pytest
from dbus_next import Message, MessageType, Variant
from dbus_next.aio import MessageBus

from automater.portal import SERVICE, PortalConnection, PortalPointer


class FakePortal:
    def __init__(self, address):
        self.address = address
        self.calls = []
        self.denied = False
        self.hold_start = False
        self.pointer_types = 2
        self.monitor_types = 1
        self.missing_interface = ""
        self.started = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        assert self.started.wait(3)

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        async def connect():
            self.bus = await MessageBus(bus_address=self.address).connect()
            await self.bus.request_name(SERVICE)
            self.bus.add_message_handler(self.handle)
            self.started.set()

        self.loop.run_until_complete(connect())
        self.loop.run_forever()
        self.bus.disconnect()
        self.loop.close()

    def handle(self, message):
        if message.message_type != MessageType.METHOD_CALL or message.destination != SERVICE:
            return
        self.calls.append((message.member, message.signature, message.body))
        if message.interface == "org.freedesktop.DBus.Properties" and message.member == "GetAll":
            if self.missing_interface and message.body[0].endswith(self.missing_interface):
                self.bus.send(
                    Message.new_error(
                        message,
                        "org.freedesktop.DBus.Error.UnknownInterface",
                        "Interface unavailable",
                    )
                )
                return True
            props = {"version": Variant("u", 1)}
            if message.body[0].endswith("RemoteDesktop"):
                props["AvailableDeviceTypes"] = Variant("u", self.pointer_types)
            else:
                props["AvailableSourceTypes"] = Variant("u", self.monitor_types)
            self.bus.send(Message.new_method_return(message, "a{sv}", [props]))
            return True
        if message.member in ("NotifyPointerMotionAbsolute", "Close"):
            self.bus.send(Message.new_method_return(message))
            return True
        options = message.body[-1]
        token = options["handle_token"].value
        sender = message.sender[1:].replace(".", "_")
        path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        self.bus.send(Message.new_method_return(message, "o", [path]))
        results = {}
        if message.member == "CreateSession":
            self.session = f"/org/freedesktop/portal/desktop/session/{sender}/test"
            results = {"session_handle": Variant("o", self.session)}
        if message.member == "Start":
            if self.hold_start:
                return True
            results = {
                "devices": Variant("u", 2),
                "streams": Variant(
                    "a(ua{sv})",
                    [
                        [
                            42,
                            {
                                "position": Variant("(ii)", [-1920, 0]),
                                "size": Variant("(ii)", [1920, 1080]),
                            },
                        ]
                    ],
                ),
            }
        self.bus.send(
            Message.new_signal(
                path,
                "org.freedesktop.portal.Request",
                "Response",
                "ua{sv}",
                [1 if self.denied else 0, results],
            )
        )
        return True

    def revoke(self):
        self.loop.call_soon_threadsafe(
            lambda: self.bus.send(
                Message.new_signal(
                    self.session, "org.freedesktop.portal.Session", "Closed", "a{sv}", [{}]
                )
            )
        )

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(2)


@pytest.fixture
def portal_server():
    if not shutil.which("dbus-daemon"):
        pytest.skip("dbus-daemon is unavailable")
    daemon = subprocess.Popen(
        ["dbus-daemon", "--session", "--nofork", "--print-address=1"],
        stdout=subprocess.PIPE,
        text=True,
    )
    address = daemon.stdout.readline().strip()
    server = FakePortal(address)
    try:
        yield server
    finally:
        server.close()
        daemon.terminate()
        daemon.wait(timeout=3)


def connection_for(server):
    return PortalConnection(bus_address=server.address)


def cleanup(connection):
    connection.close()
    connection.thread.join(3)
    assert not connection.thread.is_alive()


def test_portal_authorization_and_coordinate_reset_over_real_bus(qtbot, portal_server):
    connection = connection_for(portal_server)
    try:
        with qtbot.waitSignal(connection.ready, timeout=4000):
            connection.connect_pointer()
        assert connection.active
        pointer = PortalPointer(connection)
        pointer.validate((-1000, 200))
        pointer.move((-1000, 200))
        pointer.close()
        assert connection.active
        assert [name for name, _, _ in portal_server.calls if name != "GetAll"][:4] == [
            "CreateSession",
            "SelectDevices",
            "SelectSources",
            "Start",
        ]
        name, signature, body = portal_server.calls[-1]
        assert name == "NotifyPointerMotionAbsolute" and signature == "oa{sv}udd"
        assert body == [connection.session, {}, 42, 920.0, 200.0]
        with pytest.raises(ValueError, match="outside"):
            pointer.validate((500, 200))
    finally:
        cleanup(connection)
    assert any(name == "Close" for name, _, _ in portal_server.calls)


def test_portal_denial_and_revocation_are_reported(qtbot, portal_server):
    portal_server.denied = True
    connection = connection_for(portal_server)
    with qtbot.waitSignal(connection.failed, timeout=4000) as result:
        connection.connect_pointer()
    assert "cancelled or denied" in result.args[0]
    cleanup(connection)
    portal_server.denied = False
    connection = connection_for(portal_server)
    try:
        with qtbot.waitSignal(connection.ready, timeout=4000):
            connection.connect_pointer()
        with qtbot.waitSignal(connection.revoked, timeout=4000):
            portal_server.revoke()
        assert not connection.active
        with pytest.raises(RuntimeError, match="Connect"):
            connection.locate((-1000, 200))
    finally:
        cleanup(connection)


def test_portal_can_cancel_an_open_permission_request(qtbot, portal_server):
    portal_server.hold_start = True
    connection = connection_for(portal_server)
    connection.connect_pointer()
    qtbot.waitUntil(
        lambda: any(name == "Start" for name, _, _ in portal_server.calls), timeout=4000
    )
    cleanup(connection)
    assert not connection.active
    assert any(name == "Close" for name, _, _ in portal_server.calls)


def test_portal_coordinate_scaling_and_missing_permission():
    connection = PortalConnection()
    with pytest.raises(RuntimeError):
        connection.locate((0, 0))
    connection.active = True
    connection.streams = [
        [1, {"position": [100, 0], "size": [2000, 1000], "logical_size": [1000, 500]}]
    ]
    assert connection.locate((1100, 500)) == (1, 500.0, 250.0)


def test_window_replay_uses_approved_portal_for_every_loop(
    qtbot, portal_server, tmp_path, monkeypatch
):
    from test_engine import Backend
    from test_gui import clean, window

    class DesktopBackend(Backend):
        startup_delay = 0
        coordinate_space = "desktop"

        def __init__(self, pointer_factory):
            super().__init__()
            self.pointer = pointer_factory()

        def prepare_start(self, point):
            self.pointer.validate(point)

        def begin_cycle(self, point):
            self.pointer.move(point)

    win = window(qtbot, tmp_path, monkeypatch)
    connection = connection_for(portal_server)
    win.portal_connection = connection
    try:
        with qtbot.waitSignal(connection.ready, timeout=4000):
            connection.connect_pointer()
        monkeypatch.setattr("automater.window.UInputBackend", DesktopBackend)
        monkeypatch.setattr("automater.pointer.capability", lambda: (False, "Wayland"))
        win.test_mode.setChecked(False)
        win.start_x.setValue(-1000)
        win.start_y.setValue(200)
        win.start_enabled.setChecked(True)
        win.start_settle.setValue(0)
        win.countdown.setValue(0)
        win.repeats.setValue(2)
        win.speed.setValue(10)
        win.toggle_play()
        qtbot.waitUntil(lambda: not win.busy, timeout=4000)
        assert [name for name, _, _ in portal_server.calls].count(
            "NotifyPointerMotionAbsolute"
        ) == 2
        assert "finished" in win.status.text()
    finally:
        clean(win)
        cleanup(connection)


def test_read_only_portal_probe_never_opens_a_session(portal_server):
    from automater.portal_probe import probe

    result = probe(portal_server.address)
    assert result["available"] and result["pointer_supported"]
    assert [member for member, _, _ in portal_server.calls] == ["GetAll", "GetAll"]


@pytest.mark.parametrize("missing", ["RemoteDesktop", "ScreenCast"])
def test_missing_portal_interfaces_fail_before_permission_ui(qtbot, portal_server, missing):
    from automater.portal_probe import probe

    portal_server.missing_interface = missing
    result = probe(portal_server.address)
    assert not result["available"] and missing in result["message"]
    connection = connection_for(portal_server)
    try:
        with qtbot.waitSignal(connection.failed, timeout=4000):
            connection.connect_pointer()
        assert not connection.active
        assert not any(member == "CreateSession" for member, _, _ in portal_server.calls)
    finally:
        cleanup(connection)


def test_portal_without_pointer_does_not_prompt_for_permission(qtbot, portal_server):
    portal_server.pointer_types = 1
    connection = connection_for(portal_server)
    try:
        with qtbot.waitSignal(connection.failed, timeout=4000):
            connection.connect_pointer()
        assert not any(member == "CreateSession" for member, _, _ in portal_server.calls)
    finally:
        cleanup(connection)


def test_doctor_portal_check_uses_only_read_only_properties(portal_server):
    result = subprocess.run(
        [sys.executable, "-m", "automater.app", "--doctor", "--check-portal"],
        env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": portal_server.address},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["pointer_portal"]["available"]
    assert [member for member, _, _ in portal_server.calls] == ["GetAll", "GetAll"]
