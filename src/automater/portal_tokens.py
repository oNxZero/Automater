"""Single-use portal restore tokens, kept out of workflow files."""

import asyncio
import fcntl
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from .storage import data_dir, write_json


class PortalTokens:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else data_dir() / "portal-pointer.json"

    @asynccontextmanager
    async def claim(self, enabled=True):
        if not enabled:
            yield None
            return
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.05)
            yield self.take()
        finally:
            os.close(fd)

    def take(self):
        try:
            with self.path.open("rb") as stream:
                content = stream.read(32769)
            self.path.unlink(missing_ok=True)
            if len(content) > 32768:
                return None
            data = json.loads(content)
            token = data.get("restore_token") if isinstance(data, dict) else None
            if (
                data.get("version") == 1
                and isinstance(token, str)
                and 0 < len(token) <= 4096
                and "\0" not in token
            ):
                return token
        except (FileNotFoundError, ValueError, AttributeError):
            return None
        return None

    def save(self, token):
        if isinstance(token, str) and 0 < len(token) <= 4096 and "\0" not in token:
            write_json({"version": 1, "restore_token": token}, self.path)

    async def forget(self):
        async with self.claim():
            pass
