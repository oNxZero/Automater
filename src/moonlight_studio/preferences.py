"""Local settings, separate from portable macro files."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .engine import PlaybackOptions
from .storage import write_json


@dataclass
class Preferences:
    device_ids: list[str] | None = None
    speed: float = 1.0
    repeats: int = 1
    countdown: int = 3
    loop_gap: float = 0.25
    capture_keys: bool = True
    capture_buttons: bool = True
    capture_motion: bool = True
    append_recording: bool = True
    test_mode: bool = False
    layout: str = "horizontal"
    start_x: int = 0
    start_y: int = 0
    start_settle_ms: float = 150
    script_directory: str | None = None

    def validate(self):
        from .models import number

        if self.script_directory is not None and (
            not isinstance(self.script_directory, str)
            or not self.script_directory
            or len(self.script_directory) > 4096
            or "\x00" in self.script_directory
            or not Path(self.script_directory).is_absolute()
        ):
            raise ValueError("Invalid script folder")

        number(self.start_settle_ms, "Cursor settle delay", 0, 10_000)
        PlaybackOptions(
            self.speed,
            self.repeats,
            self.countdown,
            self.loop_gap,
            None,
            self.start_settle_ms / 1000,
        )
        from .pointer import coordinate

        coordinate(self.start_x)
        coordinate(self.start_y)
        if self.layout not in ("horizontal", "vertical", "grid"):
            raise ValueError("Invalid workflow layout")
        if type(self.countdown) is not int:
            raise ValueError("Start delay must be a whole number")
        for field in (
            "capture_keys",
            "capture_buttons",
            "capture_motion",
            "append_recording",
            "test_mode",
        ):
            if type(getattr(self, field)) is not bool:
                raise ValueError(f"Invalid {field} setting")
        if self.device_ids is not None and (
            not isinstance(self.device_ids, list)
            or len(self.device_ids) > 1000
            or any(not isinstance(s, str) or len(s) > 2000 for s in self.device_ids)
        ):
            raise ValueError("Invalid device selections")
        return self

    def save(self, path):
        self.validate()
        data = {"version": 2, **asdict(self)}
        if len(json.dumps(data, indent=2).encode("utf-8")) > 256 * 1024:
            raise ValueError("Preferences file is too large")
        write_json(data, path)

    @classmethod
    def load(cls, path):
        if not path.exists():
            return cls()
        with path.open("rb") as stream:
            content = stream.read(256 * 1024 + 1)
        if len(content) > 256 * 1024:
            raise ValueError("Preferences file is too large")
        try:
            data = json.loads(content)
        except RecursionError as exc:
            raise ValueError("Preferences file is too deeply nested") from exc
        if (
            not isinstance(data, dict)
            or type(data.get("version")) is not int
            or data.get("version") not in (1, 2)
        ):
            raise ValueError("Unsupported preferences version")
        legacy = data.pop("version") == 1
        if set(data) - set(cls.__dataclass_fields__):
            raise ValueError("Unknown preference fields")
        try:
            result = cls(**data).validate()
            if legacy:
                result.append_recording = True
            return result
        except TypeError as exc:
            raise ValueError("Invalid preferences") from exc
