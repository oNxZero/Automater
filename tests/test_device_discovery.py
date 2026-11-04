"""Exercise the installed evdev class, including its slots and lack of a context manager."""

import errno
import os
import struct
import time

import pytest
from evdev import InputDevice, ecodes
from evdev.device import DeviceInfo as HardwareInfo

from moonlight_studio import linux_input


def real_api_device(path, fd=None, name="USB Keyboard", keys=None, phys="usb-1/input0"):
    # Only the kernel metadata is supplied by the fixture. capabilities(), read(),
    # fileno(), and close() are the real installed python-evdev implementations.
    device = InputDevice.__new__(InputDevice)
    device.path = path
    device.fd = os.open("/dev/null", os.O_RDONLY) if fd is None else fd
    device.name, device.phys, device.uniq = name, phys, ""
    device.info = HardwareInfo(3, 1234, 5678, 1)
    device._rawcapabilities = {ecodes.EV_KEY: [ecodes.KEY_A] if keys is None else keys}
    device.version, device.ff_effects_count = 1, 0
    return device


def test_discovery_real_evdev_api_and_descriptor_cleanup(monkeypatch):
    opened = []

    def factory(path):
        device = real_api_device(path)
        opened.append((device, device.fd))
        return device

    monkeypatch.setattr(linux_input, "event_paths", lambda: ["/dev/input/event99"])
    monkeypatch.setattr(linux_input, "InputDevice", factory)
    found = linux_input.devices()
    assert found[0].name == "USB Keyboard" and found[0].keyboard
    assert found[0].identifier and found[0].readable
    assert opened[0][0].fd == -1
    with pytest.raises(OSError):
        os.fstat(opened[0][1])


def test_discovery_filters_virtual_and_non_input_and_closes_them(monkeypatch):
    opened = []

    def factory(path):
        device = real_api_device(
            path,
            name=linux_input.VIRTUAL_NAME if path == "virtual" else "Power button",
            keys=[ecodes.KEY_POWER],
        )
        opened.append(device)
        return device

    monkeypatch.setattr(linux_input, "event_paths", lambda: ["virtual", "power"])
    monkeypatch.setattr(linux_input, "InputDevice", factory)
    assert linux_input.devices() == []
    assert all(d.fd == -1 for d in opened)


def test_permission_failure_is_listed_and_disconnected_node_is_ignored(monkeypatch):
    def factory(path):
        if path == "denied":
            raise PermissionError(errno.EACCES, "Access denied")
        raise FileNotFoundError(errno.ENOENT, "Device removed")

    monkeypatch.setattr(linux_input, "event_paths", lambda: ["denied", "removed"])
    monkeypatch.setattr(linux_input, "InputDevice", factory)
    found = linux_input.devices()
    assert len(found) == 1 and found[0].path == "denied"
    assert not found[0].readable and found[0].issue == "Permission needed"


def test_capability_error_still_closes_device(monkeypatch):
    opened = []

    class Broken:
        name = "Broken keyboard"

        def capabilities(self):
            raise OSError(errno.EIO, "I/O failure")

        def close(self):
            opened.append("closed")

    monkeypatch.setattr(linux_input, "event_paths", lambda: ["broken"])
    monkeypatch.setattr(linux_input, "InputDevice", lambda _: Broken())
    assert not linux_input.devices()[0].readable
    assert opened == ["closed"]


def test_stable_identity_survives_event_node_renumbering():
    first, second = real_api_device("event1"), real_api_device("event14")
    try:
        assert linux_input.device_identifier(first) == linux_input.device_identifier(second)
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("monotonic", [False, True])
def test_real_evdev_read_from_pipe_through_monitor_and_recorder(monkeypatch, monotonic):
    read_fd, write_fd = os.pipe2(os.O_NONBLOCK)
    device = real_api_device("event-pipe", read_fd)
    recorder = linux_input.Recorder()
    recorder.start()
    shortcuts, errors = [], []
    monitor = linux_input.DeviceMonitor(["event-pipe"], recorder, shortcuts.append, errors.append)

    def shortcut(action):
        shortcuts.append(action)
        monitor._stop.set()

    monitor.hotkey = shortcut
    monkeypatch.setattr(linux_input, "InputDevice", lambda _: device)
    if monotonic:
        monkeypatch.setattr(linux_input.fcntl, "ioctl", lambda *args: 0)
    try:
        monitor.start()
        stamp = (time.monotonic() if monotonic else time.time()) + 0.01
        events = [
            (ecodes.EV_KEY, ecodes.KEY_A, 1),
            (ecodes.EV_REL, ecodes.REL_X, 12),
            (ecodes.EV_KEY, ecodes.KEY_A, 0),
            (ecodes.EV_KEY, ecodes.KEY_F12, 1),
        ]
        packets = []
        for i, (kind, code, value) in enumerate(events):
            event_time = stamp + i * 0.025
            packets.append(
                struct.pack("@llHHi", int(event_time), int(event_time % 1 * 1e6), kind, code, value)
            )
        os.write(write_fd, b"".join(packets))
        monitor._thread.join(1)
        assert not monitor._thread.is_alive() and not errors
        assert shortcuts == ["stop"]
        steps = recorder.stop()
        assert [s.action for s in steps] == ["key_down", "move", "key_up", "wait"]
        assert steps[1].x == 12
        assert steps[1].delay_ms == pytest.approx(25, abs=0.2)
        assert device.fd == -1
    finally:
        monitor.stop()
        device.close()
        os.close(write_fd)


def test_monitor_open_failure_closes_already_opened_devices(monkeypatch):
    opened = real_api_device("first")

    def factory(path):
        if path == "first":
            return opened
        raise PermissionError("second device")

    monkeypatch.setattr(linux_input, "InputDevice", factory)
    monitor = linux_input.DeviceMonitor(
        ["first", "second"], linux_input.Recorder(), lambda _: None, lambda _: None
    )
    with pytest.raises(PermissionError):
        monitor.start()
    assert opened.fd == -1


@pytest.mark.parametrize("relative", [False, True])
def test_mouse_capabilities_are_described_without_claiming_absolute_capture(monkeypatch, relative):
    def factory(path):
        device = real_api_device(path, name="Pointer", keys=[ecodes.BTN_LEFT])
        if relative:
            device._rawcapabilities[ecodes.EV_REL] = [ecodes.REL_X, ecodes.REL_Y]
        return device

    monkeypatch.setattr(linux_input, "event_paths", lambda: ["pointer"])
    monkeypatch.setattr(linux_input, "InputDevice", factory)
    found = linux_input.devices()[0]
    assert found.mouse and not found.keyboard
    assert bool(found.issue) == (not relative)


def test_wheel_only_interface_is_available_for_capture(monkeypatch):
    def factory(path):
        device = real_api_device(path, name="Mouse wheel interface", keys=[])
        device._rawcapabilities[ecodes.EV_REL] = [ecodes.REL_WHEEL]
        return device

    monkeypatch.setattr(linux_input, "event_paths", lambda: ["wheel"])
    monkeypatch.setattr(linux_input, "InputDevice", factory)
    found = linux_input.devices()
    assert len(found) == 1 and found[0].mouse and found[0].readable
