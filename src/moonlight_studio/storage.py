import json
import os
import tempfile
from pathlib import Path

from .models import Script

MAX_BYTES = 32 * 1024 * 1024


def data_dir():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "moonlight-studio"


def load(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Script exceeds the 32 MiB import limit")
    try:
        with path.open("rb") as stream:
            content = stream.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise ValueError("Script exceeds the 32 MiB import limit")
        return Script.from_dict(json.loads(content.decode("utf-8")))
    except (TypeError, KeyError, RecursionError) as exc:
        raise ValueError(f"Invalid script: {exc}") from exc


def save(script, path):
    """Replace atomically; never truncate a good script if writing fails."""
    write_json(script.to_dict(), path)


def write_json(data, path):
    """Write a private JSON file atomically, also used for preferences."""
    path = Path(path)
    content = json.dumps(data, indent=2, allow_nan=False) + "\n"
    if len(content.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Script exceeds the 32 MiB file limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".moonlight-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
