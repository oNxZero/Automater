"""Versioned, data-only scripts. Importing a script never executes Python."""

import math
from dataclasses import asdict, dataclass, field

from evdev import ecodes

ACTIONS = ("key_down", "key_up", "move", "scroll", "wait")
BUTTONS = {
    "BTN_LEFT",
    "BTN_RIGHT",
    "BTN_MIDDLE",
    "BTN_SIDE",
    "BTN_EXTRA",
    "BTN_FORWARD",
    "BTN_BACK",
    "BTN_TASK",
}
KEY_CODES = {
    name: code
    for name, code in ecodes.ecodes.items()
    if (
        (
            name.startswith("KEY_")
            and name not in {"KEY_MAX", "KEY_CNT", "KEY_MIN_INTERESTING"}
            and 0 < code < ecodes.KEY_MAX
        )
        or name in BUTTONS
    )
}
MAX_STEPS = 200_000


def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    if not low <= value <= high or not math.isfinite(value):
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


@dataclass(frozen=True)
class Step:
    delay_ms: float = 100
    action: str = "wait"
    code: str = ""
    x: int = 0
    y: int = 0
    enabled: bool = True
    delay_max_ms: float | None = None
    standalone: bool = False

    def __post_init__(self):
        number(self.delay_ms, "Delay (ms)", 0, 3_600_000)
        if self.delay_max_ms is not None:
            number(self.delay_max_ms, "Maximum delay (ms)", self.delay_ms, 3_600_000)
        if self.action not in ACTIONS:
            raise ValueError("Unknown action")
        if not isinstance(self.code, str) or len(self.code) > 80:
            raise ValueError("Invalid key code")
        if self.action.startswith("key_") and self.code not in KEY_CODES:
            raise ValueError("Choose a Linux KEY_* or supported BTN_* code")
        for name, value in (("X", self.x), ("Y", self.y)):
            number(value, name, -32767, 32767)
            if not isinstance(value, int):
                raise ValueError(f"{name} must be a whole number")
        if type(self.enabled) is not bool:
            raise ValueError("Enabled must be true or false")
        if type(self.standalone) is not bool:
            raise ValueError("Standalone must be true or false")

    @property
    def maximum_ms(self):
        return self.delay_ms if self.delay_max_ms is None else self.delay_max_ms

    def sample_delay(self, rng):
        return (
            self.delay_ms
            if self.delay_max_ms is None
            else rng.uniform(self.delay_ms, self.delay_max_ms)
        )

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) - set(cls.__dataclass_fields__):
            raise ValueError("Invalid step fields")
        return cls(**data)


@dataclass
class Script:
    name: str = "Untitled script"
    notes: str = ""
    steps: list[Step] = field(default_factory=list)
    version: int = 1
    start: dict | None = None

    def validate(self):
        if type(self.version) is not int or self.version not in (1, 2):
            raise ValueError("Unsupported script version; expected version 1 or 2")
        if not isinstance(self.name, str) or not 1 <= len(self.name.strip()) <= 120:
            raise ValueError("Script name must contain 1–120 characters")
        if not isinstance(self.notes, str) or len(self.notes) > 20_000:
            raise ValueError("Notes must contain at most 20,000 characters")
        if not isinstance(self.steps, list) or len(self.steps) > MAX_STEPS:
            raise ValueError(f"A script can contain at most {MAX_STEPS:,} steps")
        if not all(isinstance(step, Step) for step in self.steps):
            raise ValueError("Invalid script steps")
        if self.start is not None:
            from .pointer import coordinate

            if not isinstance(self.start, dict) or set(self.start) != {
                "x",
                "y",
                "settle_ms",
                "space",
            }:
                raise ValueError("Invalid starting point fields")
            coordinate(self.start["x"])
            coordinate(self.start["y"])
            number(self.start["settle_ms"], "Cursor settle delay", 0, 10_000)
            if self.start["space"] not in ("desktop", "window"):
                raise ValueError("Invalid starting coordinate space")
        return self

    @property
    def duration_ms(self):
        return sum(s.delay_ms for s in self.steps if s.enabled)

    def warnings(self):
        held, warnings = set(), []
        for i, step in enumerate(self.steps, 1):
            if not step.enabled:
                continue
            if step.action == "key_down":
                if step.code in held:
                    warnings.append(f"Step {i}: repeated press of {step.code}")
                held.add(step.code)
            elif step.action == "key_up":
                if step.code not in held:
                    warnings.append(f"Step {i}: {step.code} released without a press")
                held.discard(step.code)
        if held:
            warnings.append("Released automatically at loop end: " + ", ".join(sorted(held)))
        return warnings

    def to_dict(self):
        self.validate()
        data = asdict(self)
        if self.start is not None or any(
            s.delay_max_ms is not None
            or s.standalone
            or KEY_CODES.get(s.code, 0) >= ecodes.BTN_TRIGGER
            for s in self.steps
        ):
            data["version"] = 2
        if data["version"] == 1:
            data.pop("start")
            for step in data["steps"]:
                step.pop("delay_max_ms")
                step.pop("standalone")
        return data

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) - {"name", "notes", "steps", "version", "start"}:
            raise ValueError("Invalid script fields")
        if "version" not in data or not isinstance(data.get("steps"), list):
            raise ValueError("Script requires a version and a steps array")
        if len(data["steps"]) > MAX_STEPS:
            raise ValueError("Script is too large")
        return cls(**{**data, "steps": [Step.from_dict(s) for s in data["steps"]]}).validate()
