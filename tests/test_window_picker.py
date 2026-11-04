import json
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog
from test_gui import clean, window

from moonlight_studio.open_windows import DesktopWindow, GuardedDesktopBackend, discover_windows
from moonlight_studio.window_picker import WindowPicker
from moonlight_studio.x11 import WindowInfo


def seed_windows(win):
    native = DesktopWindow("native-1", "Sober", 123, ("org.vinegarhq.Sober",))
    xclient = WindowInfo(100, "Notes", 456, ("notes", "Notes"))
    with win.window_observer.lock:
        win.window_observer.windows = [native]
        win.window_observer.active_id = native.id
        win.window_observer.available = True
    win.x11_targets = [xclient]
    win.desktop_windows_changed()
    return native, xclient


def test_picker_searches_open_windows_by_title_and_application(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    native, xclient = seed_windows(win)
    picker = WindowPicker(win, lambda: None)
    qtbot.addWidget(picker)
    picker.set_windows([native, xclient])
    picker.show()
    picker.search.setText("vinegar")
    assert picker.list.item(0).isHidden() is False
    assert picker.list.item(1).isHidden()
    assert picker.list.currentItem().data(Qt.UserRole) == native
    picker.accept_choice()
    assert picker.result() == QDialog.Accepted and picker.choice == native
    clean(win)


def test_picker_explains_native_window_uses_active_desktop(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    native, _ = seed_windows(win)
    win.mode.setCurrentIndex(1)
    picker = WindowPicker(win, lambda: None)
    qtbot.addWidget(picker)
    picker.set_windows([native])
    assert picker.use.text() == "Use on active desktop"
    assert "Keep it focused" in picker.hint.text()
    picker.search.setText("no such window")
    assert not picker.use.isEnabled()
    clean(win)


def test_closed_desktop_target_is_retained_as_unavailable_instead_of_unrestricted(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    native, _ = seed_windows(win)
    win.target.setCurrentIndex(win.target_index(native))
    with win.window_observer.lock:
        win.window_observer.windows = []
    win.desktop_windows_changed()
    assert win.target.currentData() == native
    assert native not in win.available_targets
    assert "Unavailable" in win.target.currentText()
    win.new_script()
    win.target.setCurrentIndex(0)
    win.desktop_windows_changed()
    win.document_tabs.setCurrentIndex(0)
    assert win.target.currentData() == native
    assert "Unavailable" in win.target.currentText()
    clean(win)


def test_window_discovery_merges_kde_x11_without_duplicates_or_own_window(
    qtbot, tmp_path, monkeypatch
):
    import os

    win = window(qtbot, tmp_path, monkeypatch)
    native, _ = seed_windows(win)
    same = WindowInfo(200, native.title, native.pid, native.wm_class)
    own = WindowInfo(201, "Moonlight Studio", os.getpid(), ("studio",))
    assert discover_windows([same, own], win.window_observer) == [native]
    clean(win)


def test_focus_loss_stops_new_inputs_but_allows_cleanup_releases():
    import pytest
    from test_engine import Backend

    from moonlight_studio.models import Step

    backend = Backend()
    active = [True]

    def check():
        if not active[0]:
            raise RuntimeError("Lost focus")

    guarded = GuardedDesktopBackend(backend, check)
    guarded.send(Step(0, "key_down", "KEY_A"))
    active[0] = False
    with pytest.raises(RuntimeError, match="Lost focus"):
        guarded.send(Step(0, "move", x=20))
    guarded.send(Step(0, "key_up", "KEY_A"))
    guarded.close()
    assert [s.action for s in backend.events] == ["key_down", "key_up"]
    assert backend.closed


# Reuse the private D-Bus fixture; this test never changes real compositor state.
from test_portal import portal_server  # noqa: E402, F401


def test_kde_discovery_and_focus_updates_over_private_bus(qtbot, portal_server):  # noqa: F811
    import asyncio

    from dbus_next import Message

    from moonlight_studio.open_windows import CALLBACK, KWIN, WindowObserver

    server = portal_server
    calls = []
    state = {
        "active": "native",
        "windows": [
            {"id": "native", "title": "Game", "pid": 123, "app": "game"},
            {"id": "notes", "title": "Notes", "pid": 456, "app": "notes"},
        ],
    }

    async def publish():
        return await server.bus.call(
            Message(
                destination=server.callback,
                path="/Windows",
                interface=CALLBACK,
                member="Snapshot",
                signature="s",
                body=[json.dumps(state)],
            )
        )

    def kwin(message):
        if message.destination != KWIN:
            return
        calls.append(message.member)
        if message.member == "loadScript":
            from pathlib import Path

            script = Path(message.body[0]).read_text()
            server.callback = json.loads(re.search(r'callDBus\(("[^"]+")', script).group(1))
            server.bus.send(Message.new_method_return(message, "i", [1]))
        elif message.member == "run":
            server.bus.send(Message.new_method_return(message))
            server.loop.create_task(publish())
        elif message.member == "unloadScript":
            server.bus.send(Message.new_method_return(message, "b", [True]))
        return True

    async def setup():
        await server.bus.request_name(KWIN)
        server.bus.add_message_handler(kwin)

    asyncio.run_coroutine_threadsafe(setup(), server.loop).result(2)
    observer = WindowObserver(bus_address=server.address)
    try:
        observer.start()
        qtbot.waitUntil(lambda: observer.snapshot()[2], timeout=4000)
        target = observer.snapshot()[0][0]
        observer.check_focus(target)
        state["active"] = "notes"
        asyncio.run_coroutine_threadsafe(publish(), server.loop).result(2)
        import pytest

        with pytest.raises(RuntimeError, match="lost focus"):
            observer.check_focus(target)
        state["windows"] = []
        asyncio.run_coroutine_threadsafe(publish(), server.loop).result(2)
        with pytest.raises(RuntimeError, match="closed"):
            observer.check_focus(target)
    finally:
        observer.close()
        observer.thread.join(4)
    assert not observer.thread.is_alive()
    assert calls == ["loadScript", "run", "unloadScript"]
    assert not observer.snapshot()[2]


def test_native_window_choice_switches_to_supported_desktop_mode(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    native, _ = seed_windows(win)
    win.mode.setCurrentIndex(1)

    def choose(picker):
        picker.choice = native
        return QDialog.Accepted

    monkeypatch.setattr(WindowPicker, "exec", choose)
    win.choose_open_window()
    assert win.mode.currentIndex() == 0
    assert win.target.currentData() == native
    clean(win)


def test_selected_desktop_window_requires_focus_before_any_input(qtbot, tmp_path, monkeypatch):
    from test_engine import Backend

    win = window(qtbot, tmp_path, monkeypatch)
    native, _ = seed_windows(win)
    win.target.setCurrentIndex(win.target_index(native))
    with win.window_observer.lock:
        win.window_observer.active_id = "another-window"
    backend = Backend()

    def factory():
        return backend

    factory.startup_delay = 0
    monkeypatch.setattr("moonlight_studio.window.UInputBackend", factory)
    win.test_mode.setChecked(False)
    win.countdown.setValue(0)
    win.toggle_play()
    qtbot.waitUntil(lambda: not win.busy, timeout=2000)
    assert backend.events == [] and backend.closed
    assert "lost focus" in win.status.text()
    clean(win)
