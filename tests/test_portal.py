"""Real D-Bus serialization against a private fake portal; never controls a desktop."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

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
        self.remote_version = 1
        self.restore_token = None
        self.denied_member = ""
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
                props["version"] = Variant("u", self.remote_version)
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
            if self.restore_token is not None:
                results["restore_token"] = Variant("s", self.restore_token)
        self.bus.send(
            Message.new_signal(
                path,
                "org.freedesktop.portal.Request",
                "Response",
                "ua{sv}",
                [1 if self.denied or message.member == self.denied_member else 0, results],
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


def connection_for(server, token_path=None):
    return PortalConnection(bus_address=server.address, token_path=token_path)


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


def test_persistent_approval_uses_remote_desktop_and_rotates_token(qtbot, portal_server, tmp_path):
    from automater.portal_tokens import PortalTokens

    path = tmp_path / "portal-pointer.json"
    PortalTokens(path).save("first-token")
    portal_server.remote_version = 2
    portal_server.restore_token = "second-token"
    connection = connection_for(portal_server, path)
    try:
        with qtbot.waitSignal(connection.ready, timeout=4000):
            connection.connect_pointer()
        options = next(
            body[-1] for member, _, body in portal_server.calls if member == "SelectDevices"
        )
        assert options["restore_token"].value == "first-token"
        assert options["persist_mode"].value == 2
        sources = next(
            body[-1] for member, _, body in portal_server.calls if member == "SelectSources"
        )
        assert "restore_token" not in sources and "persist_mode" not in sources
        assert json.loads(path.read_text())["restore_token"] == "second-token"
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        cleanup(connection)
    portal_server.calls.clear()
    portal_server.restore_token = "third-token"
    connection = connection_for(portal_server, path)
    try:
        with qtbot.waitSignal(connection.ready, timeout=4000):
            connection.connect_pointer()
        options = next(
            body[-1] for member, _, body in portal_server.calls if member == "SelectDevices"
        )
        assert options["restore_token"].value == "second-token"
        assert json.loads(path.read_text())["restore_token"] == "third-token"
    finally:
        cleanup(connection)


def test_denied_restore_does_not_reuse_consumed_token(qtbot, portal_server, tmp_path):
    from automater.portal_tokens import PortalTokens

    path = tmp_path / "portal-pointer.json"
    PortalTokens(path).save("consumed-token")
    portal_server.remote_version = 2
    portal_server.denied_member = "Start"
    connection = connection_for(portal_server, path)
    try:
        with qtbot.waitSignal(connection.failed, timeout=4000):
            connection.connect_pointer()
        assert not connection.active
        assert not path.exists()
    finally:
        cleanup(connection)


def test_older_portal_never_receives_persistence_options(qtbot, portal_server, tmp_path):
    path = tmp_path / "portal-pointer.json"
    connection = connection_for(portal_server, path)
    try:
        with qtbot.waitSignal(connection.ready, timeout=4000):
            connection.connect_pointer()
        options = next(
            body[-1] for member, _, body in portal_server.calls if member == "SelectDevices"
        )
        assert "restore_token" not in options and "persist_mode" not in options
        assert not path.exists()
    finally:
        cleanup(connection)


def test_cli_pointer_setup_runs_without_qt_and_remembers_approval(portal_server, tmp_path):
    portal_server.remote_version = 2
    portal_server.restore_token = "cli-token"
    code = """
import sys
from automater.app import main
result = main(['pointer', 'setup'])
assert not any(name.startswith('PySide6') for name in sys.modules)
raise SystemExit(result)
"""
    env = {
        **os.environ,
        "DBUS_SESSION_BUS_ADDRESS": portal_server.address,
        "XDG_CONFIG_HOME": str(tmp_path),
    }
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0, result.stderr
    path = tmp_path / "automater/portal-pointer.json"
    assert json.loads(path.read_text())["restore_token"] == "cli-token"
    forgotten = subprocess.run(
        [sys.executable, "-m", "automater", "pointer", "forget"],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert forgotten.returncode == 0, forgotten.stderr
    assert not path.exists()


@pytest.mark.parametrize("cancel", [False, True])
def test_run_connects_pointer_automatically_and_honors_cancel(
    qtbot, portal_server, tmp_path, monkeypatch, cancel
):
    from test_engine import Backend
    from test_gui import clean, window

    from automater.portal import PortalConnection as Connection

    calls = []

    class DesktopBackend(Backend):
        startup_delay = 0
        coordinate_space = "desktop"

        def __init__(self, pointer_factory):
            super().__init__()
            self.pointer = pointer_factory()
            calls.append(self)

        def prepare_start(self, point):
            self.pointer.validate(point)

        def begin_cycle(self, point):
            self.pointer.move(point)

    win = window(qtbot, tmp_path, monkeypatch)
    portal_server.hold_start = cancel
    monkeypatch.setattr(
        "automater.portal.PortalConnection",
        lambda parent, token_path: Connection(
            parent, bus_address=portal_server.address, token_path=token_path
        ),
    )
    monkeypatch.setattr("automater.window.UInputBackend", DesktopBackend)
    monkeypatch.setattr("automater.window.session_type", lambda: "wayland")
    monkeypatch.setattr("automater.pointer.capability", lambda: (False, "Wayland"))
    win.test_mode.setChecked(False)
    win.start_x.setValue(-1000)
    win.start_y.setValue(200)
    win.start_enabled.setChecked(True)
    win.start_settle.setValue(0)
    win.countdown.setValue(0)
    win.speed.setValue(10)
    try:
        win.toggle_play()
        assert win.connecting_pointer and win.busy
        if cancel:
            qtbot.waitUntil(
                lambda: any(member == "Start" for member, _, _ in portal_server.calls), timeout=4000
            )
            win.stop()
            qtbot.waitUntil(lambda: not win.busy, timeout=4000)
            assert not calls and not win.play_after_pointer
        else:
            qtbot.waitUntil(lambda: not win.busy, timeout=4000)
            assert calls and "finished" in win.status.text()
    finally:
        clean(win)
        if win.portal_connection:
            cleanup(win.portal_connection)


def test_cli_saved_start_connects_portal_and_moves_before_playback(
    portal_server, tmp_path, monkeypatch
):
    from automater.app import main
    from automater.models import Script, Step
    from automater.storage import save

    events = []

    class Backend:
        coordinate_space = "desktop"

        def __init__(self, pointer_factory):
            self.pointer = pointer_factory()

        def prepare_start(self, point):
            self.pointer.validate(point)

        def begin_cycle(self, point):
            self.pointer.move(point)
            events.append("position")

        def check(self):
            pass

        def send(self, step):
            events.append(step.action)

        def close(self):
            events.append("closed")

    monkeypatch.setattr("automater.linux_input.UInputBackend", Backend)
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    monkeypatch.setattr("automater.pointer.capability", lambda: (False, "Wayland"))
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", portal_server.address)
    path = tmp_path / "start.json"
    save(
        Script(
            steps=[Step(0, "key_down", "KEY_A"), Step(1, "key_up", "KEY_A")],
            version=2,
            start={"x": -1000, "y": 200, "space": "desktop", "settle_ms": 0},
        ),
        path,
    )
    with tempfile.TemporaryDirectory(prefix="automater-cli-portal-") as runtime:
        monkeypatch.setenv("XDG_RUNTIME_DIR", runtime)
        assert main(["run", str(path), "--quiet"]) == 0
    assert events == ["position", "key_down", "key_up", "closed"]
    assert any(member == "NotifyPointerMotionAbsolute" for member, _, _ in portal_server.calls)


def test_cli_stop_cancels_pending_portal_permission(portal_server, tmp_path, monkeypatch):
    from automater import cli_control
    from automater.models import Script, Step
    from automater.storage import save

    portal_server.hold_start = True
    path = tmp_path / "start.json"
    save(
        Script(
            steps=[Step(0)],
            version=2,
            start={"x": -1000, "y": 200, "space": "desktop", "settle_ms": 0},
        ),
        path,
    )
    code = """
import os, sys
os.geteuid = lambda: 1000
from automater.app import main
raise SystemExit(main(sys.argv[1:]))
"""
    with tempfile.TemporaryDirectory(prefix="automater-cli-portal-") as runtime:
        monkeypatch.setenv("XDG_RUNTIME_DIR", runtime)
        env = {
            **os.environ,
            "DBUS_SESSION_BUS_ADDRESS": portal_server.address,
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_SESSION_TYPE": "wayland",
        }
        env.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
        process = subprocess.Popen(
            [sys.executable, "-c", code, "run", str(path)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 5
            while not any(member == "Start" for member, _, _ in portal_server.calls):
                assert process.poll() is None, process.communicate()
                assert time.monotonic() < deadline
                time.sleep(0.01)
            assert cli_control.request("status")["phase"] == "pointer_permission"
            stopped = subprocess.run(
                [sys.executable, "-m", "automater", "stop"],
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
            )
            assert stopped.returncode == 0, stopped.stderr
            assert process.wait(timeout=5) == 130
        finally:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=5)
    assert any(member == "Close" for member, _, _ in portal_server.calls)
