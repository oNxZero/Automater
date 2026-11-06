"""Local control socket for the lifetime of a CLI run."""

import fcntl
import json
import os
import socket
import stat
import struct
from contextlib import contextmanager
from pathlib import Path


class AlreadyRunning(RuntimeError):
    pass


def runtime_directory():
    configured = os.environ.get("XDG_RUNTIME_DIR", "")
    root = Path(configured) if configured and Path(configured).is_absolute() else Path("/tmp")
    folder = root / f"automater-cli-{os.getuid()}"
    folder.mkdir(mode=0o700, exist_ok=True)
    info = folder.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError(f"CLI runtime directory must be owned by you with mode 0700: {folder}")
    return folder


def read_line(connection, limit=32768):
    data = bytearray()
    while b"\n" not in data:
        chunk = connection.recv(min(4096, limit + 1 - len(data)))
        if not chunk:
            raise EOFError("CLI control connection closed without a response")
        data.extend(chunk)
        if len(data) > limit:
            raise ValueError("CLI control message is too large")
    return bytes(data).split(b"\n", 1)[0]


@contextmanager
def listen():
    folder = runtime_directory()
    fd = os.open(folder / "run.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError("Invalid CLI lock file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AlreadyRunning(
                "A CLI workflow is already running. Use automater stop first."
            ) from exc
        path = folder / "run.sock"
        path.unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path))
            os.chmod(path, 0o600)
            server.listen(4)
            server.settimeout(0.05)
            try:
                yield server
            finally:
                path.unlink(missing_ok=True)
    finally:
        # Keep the lock file so concurrent launches always lock the same inode.
        os.close(fd)


def serve(server, status, stop):
    try:
        connection, _ = server.accept()
    except TimeoutError:
        return
    with connection:
        try:
            connection.settimeout(0.25)
            _, uid, _ = struct.unpack(
                "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
            if uid != os.getuid():
                return
            command = read_line(connection, 32).decode("ascii")
            if command == "stop":
                stop()
            elif command != "status":
                raise ValueError("Unknown CLI control command")
            connection.sendall((json.dumps(status()) + "\n").encode())
        except (OSError, ValueError, EOFError):
            return


def request(command):
    path = runtime_directory() / "run.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(1)
        try:
            connection.connect(str(path))
        except (FileNotFoundError, ConnectionRefusedError):
            return None
        try:
            connection.sendall(command.encode("ascii") + b"\n")
            result = json.loads(read_line(connection))
        except (ConnectionResetError, BrokenPipeError, EOFError):
            return None
        if not isinstance(result, dict) or result.get("pid") is None:
            raise ValueError("Invalid CLI status response")
        return result
