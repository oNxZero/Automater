"""Managed game display. This transport never opens the host X server for injection."""

import json
import os
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import KEY_CODES
from .x11 import BUTTON_MAP, WindowInfo

MAX_MESSAGE = 65536


@dataclass(frozen=True)
class SessionAddress:
    socket_path: str
    nonce: str


class SessionRPC:
    def __init__(self, address):
        self.address = address
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(2)
        try:
            self.socket.connect(address.socket_path)
            self.reader = self.socket.makefile("rb")
        except Exception:
            self.socket.close()
            raise

    def call(self, operation, **values):
        packet = (
            json.dumps(
                {"nonce": self.address.nonce, "op": operation, **values}, allow_nan=False
            ).encode()
            + b"\n"
        )
        if len(packet) > MAX_MESSAGE:
            raise ValueError("Game session request is too large")
        self.socket.sendall(packet)
        reply = self.reader.readline(MAX_MESSAGE + 1)
        if not reply or len(reply) > MAX_MESSAGE or not reply.endswith(b"\n"):
            raise RuntimeError("The isolated game session disconnected")
        result = json.loads(reply)
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "Game session request failed"))
        return result.get("value")

    def close(self):
        self.reader.close()
        self.socket.close()


class IsolatedBackend:
    coordinate_space = "window"

    def __init__(self, address, target):
        self.rpc = SessionRPC(address)
        self.next_check = 0.0
        try:
            self.rpc.call("bind", target=asdict(target))
        except Exception:
            self.rpc.close()
            raise

    def prepare(self, steps):
        for step in steps:
            if not step.enabled:
                continue
            if step.action.startswith("key_"):
                if step.code.startswith("BTN_") and step.code not in BUTTON_MAP:
                    raise ValueError(f"{step.code} is unsupported in this game session")
                if not step.code.startswith("BTN_") and not 8 <= KEY_CODES[step.code] + 8 <= 255:
                    raise ValueError(f"{step.code} cannot be mapped to this game's X11 keyboard")
            if step.action == "scroll" and max(abs(step.x), abs(step.y)) > 100:
                raise ValueError("Scroll is limited to 100 notches per event in isolated mode")

    def check(self):
        if time.monotonic() >= self.next_check:
            self.rpc.call("check")
            self.next_check = time.monotonic() + 0.25

    def prepare_start(self, point):
        self.rpc.call("validate_point", point=list(point))

    def begin_cycle(self, point):
        self.rpc.call("position", point=list(point))

    def send(self, step):
        if step.action != "wait":
            self.rpc.call("send", step=asdict(step))

    def close(self):
        try:
            self.rpc.call("release")
        finally:
            self.rpc.close()


def application_command(sober=True, custom=""):
    if sober:
        executable = shutil.which("flatpak")
        if not executable:
            raise RuntimeError("Install Flatpak and Sober before launching this profile")
        active = subprocess.run(
            [executable, "ps", "--columns=application"],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        if "org.vinegarhq.Sober" in {line.strip() for line in active.stdout.splitlines()}:
            raise RuntimeError(
                "Close your existing Sober instance first. A running game cannot be moved into a separate display."
            )
        return [
            executable,
            "run",
            "--nosocket=wayland",
            "--socket=x11",
            "--env=SDL_VIDEODRIVER=x11",
            "org.vinegarhq.Sober",
        ]
    command = shlex.split(custom)
    if not command or not shutil.which(command[0]):
        raise ValueError("Choose an executable command, for example /path/to/game --option")
    return command


class GameSession:
    def __init__(self):
        self.process = None
        self.address = None
        self.directory = None
        self.log = deque(maxlen=200)
        self.started_at = 0.0

    def launch(self, command, width=1280, height=720):
        if self.process and self.process.poll() is None:
            raise RuntimeError("A game session is already open")
        gamescope = shutil.which("gamescope")
        if not gamescope:
            raise RuntimeError(
                "Install Gamescope with your distribution's package manager to use a separate game session"
            )
        if (
            type(width) is not int
            or type(height) is not int
            or not 640 <= width <= 3840
            or not 480 <= height <= 2160
        ):
            raise ValueError("Unsupported game resolution")
        self.directory = Path(tempfile.mkdtemp(prefix="automater-game-"))
        self.address = SessionAddress(str(self.directory / "input.sock"), secrets.token_hex(24))
        args = [
            gamescope,
            "-w",
            str(width),
            "-h",
            str(height),
            "-W",
            str(width),
            "-H",
            str(height),
            "-r",
            "60",
            "-o",
            "60",
            "--",
            sys.executable,
            "-m",
            "automater.isolated_worker",
            "--socket",
            self.address.socket_path,
            "--nonce",
            self.address.nonce,
            "--host-display",
            os.environ.get("DISPLAY", ""),
            "--",
            *command,
        ]
        try:
            self.process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
            )
        except Exception:
            shutil.rmtree(self.directory)
            raise
        self.started_at = time.monotonic()
        self.log.clear()
        process = self.process

        def read_log():
            for line in iter(lambda: process.stdout.readline(4096), ""):
                self.log.append(line.rstrip()[:1000])
            process.stdout.close()

        threading.Thread(target=read_log, daemon=True).start()

    def windows(self):
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError(
                "The game session is not running. Open Session diagnostics for details."
            )
        rpc = SessionRPC(self.address)
        try:
            return [
                WindowInfo(**{**value, "wm_class": tuple(value["wm_class"])})
                for value in rpc.call("windows")
            ]
        finally:
            rpc.close()

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def cleanup_finished(self):
        if self.directory and (self.process is None or self.process.poll() is not None):
            shutil.rmtree(self.directory, ignore_errors=True)
