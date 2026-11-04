"""Versioned, data-only scripts. Importing a script never executes Python."""

import math
import re
from dataclasses import asdict, dataclass, field

from evdev import ecodes

ACTIONS = ("key_down", "key_up", "move", "scroll", "wait", "note")
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
    title: str = ""
    text: str = ""
    group_id: str = ""

    def __post_init__(self):
        for value, name, limit in ((self.title, "Note title", 120), (self.text, "Note text", 4000)):
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError(f"{name} must contain at most {limit:,} characters")
        if not isinstance(self.group_id, str) or (
            self.group_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.group_id)
        ):
            raise ValueError("Invalid workflow group identity")
        if self.action == "note" and (self.delay_ms != 0 or self.delay_max_ms is not None):
            raise ValueError("Notes are visual only and must have zero delay")
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
    def runnable(self):
        return self.enabled and self.action != "note"

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
    groups: dict = field(default_factory=dict)

    def validate(self):
        if type(self.version) is not int or self.version not in (1, 2, 3, 4):
            raise ValueError("Unsupported script version; expected version 1, 2, 3 or 4")
        if not isinstance(self.name, str) or not 1 <= len(self.name.strip()) <= 120:
            raise ValueError("Script name must contain 1–120 characters")
        if not isinstance(self.notes, str) or len(self.notes) > 20_000:
            raise ValueError("Notes must contain at most 20,000 characters")
        if not isinstance(self.steps, list) or len(self.steps) > MAX_STEPS:
            raise ValueError(f"A script can contain at most {MAX_STEPS:,} steps")
        if not all(isinstance(step, Step) for step in self.steps):
            raise ValueError("Invalid script steps")
        if not isinstance(self.groups, dict) or len(self.groups) > 2000:
            raise ValueError("A workflow can contain at most 2,000 visual groups")
        for identity, group in self.groups.items():
            if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identity):
                raise ValueError("Invalid workflow group identity")
            if not isinstance(group, dict) or set(group) not in (
                {"name", "color"},
                {"name", "color", "notes"},
            ):
                raise ValueError("Invalid workflow group fields")
            if not isinstance(group["name"], str) or not 1 <= len(group["name"].strip()) <= 120:
                raise ValueError("Group names must contain 1–120 characters")
            if not isinstance(group["color"], str) or not re.fullmatch(
                r"#[0-9a-fA-F]{6}", group["color"]
            ):
                raise ValueError("Choose a valid group color")
            if not isinstance(group.get("notes", ""), str) or len(group.get("notes", "")) > 20000:
                raise ValueError("Group notes must contain at most 20,000 characters")
        if any(step.group_id and step.group_id not in self.groups for step in self.steps):
            raise ValueError("Workflow contains an undefined visual group")
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

    def migrate_note_cards(self):
        """Move legacy card text onto an adjacent action's group, preserving inputs."""
        from dataclasses import replace
        from uuid import uuid4

        if not any(step.action == "note" for step in self.steps):
            return self
        steps = [step for step in self.steps if step.action != "note"]
        groups = {key: dict(value) for key, value in self.groups.items()}
        after, note_parts = 0, []
        existing_members = {value.group_id for value in steps if value.group_id}
        for step in self.steps:
            if step.action != "note":
                after += 1
                continue
            text = (step.title + "\n" + step.text).strip()
            if not steps:
                note_parts.append(text)
                continue
            index = min(after, len(steps) - 1)
            identity = (
                (step.group_id if step.group_id in existing_members else "")
                or steps[index].group_id
                or step.group_id
                or uuid4().hex
            )
            metadata = groups.setdefault(
                identity, {"name": step.title or "Imported notes", "color": "#e8c58a"}
            )
            combined = "\n\n".join(value for value in (metadata.get("notes", ""), text) if value)
            if len(combined) > 20000:
                note_parts.append(text)
            else:
                metadata["notes"] = combined
            if identity not in existing_members:
                steps[index] = replace(steps[index], group_id=identity)
                existing_members.add(identity)
        notes = "\n\n".join(value for value in (self.notes, *note_parts) if value)
        if len(notes) > 20000:
            raise ValueError(
                "Imported note text exceeds the workflow description limit; the original file has not been changed"
            )
        used = {step.group_id for step in steps if step.group_id}
        return replace(
            self,
            steps=steps,
            groups={key: value for key, value in groups.items() if key in used},
            notes=notes,
        ).validate()

    @property
    def duration_ms(self):
        return sum(s.delay_ms for s in self.steps if s.runnable)

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
            data["version"] = max(data["version"], 2)
        if self.groups or any(
            s.action == "note" or s.group_id or s.title or s.text for s in self.steps
        ):
            data["version"] = max(data["version"], 3)
        if any(group.get("notes") for group in self.groups.values()):
            data["version"] = max(data["version"], 4)
        for group in data["groups"].values():
            if not group.get("notes"):
                group.pop("notes", None)
        if data["version"] < 3:
            data.pop("groups")
        for step in data["steps"]:
            for field_name in ("title", "text", "group_id"):
                if not step[field_name]:
                    step.pop(field_name)
        if data["version"] == 1:
            data.pop("start")
            for step in data["steps"]:
                step.pop("delay_max_ms")
                step.pop("standalone")
        return data

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) - {
            "name",
            "notes",
            "steps",
            "version",
            "start",
            "groups",
        }:
            raise ValueError("Invalid script fields")
        if "version" not in data or not isinstance(data.get("steps"), list):
            raise ValueError("Script requires a version and a steps array")
        if len(data["steps"]) > MAX_STEPS:
            raise ValueError("Script is too large")
        return (
            cls(**{**data, "steps": [Step.from_dict(s) for s in data["steps"]]})
            .validate()
            .migrate_note_cards()
        )
