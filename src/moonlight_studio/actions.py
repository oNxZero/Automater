"""Data-only authoring and bounded selection clipboard helpers."""

import json
from dataclasses import asdict, replace
from uuid import uuid4

from .models import KEY_CODES, MAX_STEPS, Script, Step, number

CLIPBOARD_MIME = "application/x-moonlight-studio-actions"
MAX_CLIPBOARD_BYTES = 32 * 1024 * 1024
KINDS = (
    ("Hold key / button", "key"),
    ("Mouse click", "mouse"),
    ("Timer / wait", "wait"),
    ("Move pointer", "move"),
    ("Scroll", "scroll"),
    ("Press (keep held)", "press"),
    ("Release", "release"),
)


def create_action(kind=0, code=None, delay=0, duration=100, maximum=None):
    if kind not in range(len(KINDS)):
        raise ValueError("Unknown action type")
    code = code or ("BTN_LEFT" if kind == 1 else "KEY_SPACE")
    if kind in (0, 1):
        if code not in KEY_CODES:
            raise ValueError("Choose a supported key or button")
        if kind == 1 and not code.startswith("BTN_"):
            raise ValueError("Choose a mouse button for a mouse click")
        return [Step(delay, "key_down", code), Step(duration, "key_up", code, delay_max_ms=maximum)]
    if kind == 2:
        return [Step(duration, "wait", delay_max_ms=maximum, standalone=True)]
    if kind == 3:
        return [Step(delay, "move", x=10, standalone=True)]
    if kind == 4:
        return [Step(delay, "scroll", y=1, standalone=True)]
    return [Step(delay, "key_down" if kind == 5 else "key_up", code, standalone=True)]


def encode_steps(steps, groups=None):
    if not steps or len(steps) > MAX_STEPS:
        raise ValueError("Choose between 1 and 200,000 events to copy")
    used = {step.group_id for step in steps if step.group_id}
    groups = {key: value for key, value in (groups or {}).items() if key in used}
    Script(steps=list(steps), groups=groups).validate()
    data = {
        "format": "moonlight-selection",
        "version": 1,
        "steps": [
            {
                key: value
                for key, value in asdict(step).items()
                if key not in ("title", "text", "group_id") or value
            }
            for step in steps
        ],
    }
    if groups or any(step.action == "note" for step in steps):
        data.update(version=2, groups=groups)
    content = json.dumps(data, allow_nan=False).encode()
    if len(content) > MAX_CLIPBOARD_BYTES:
        raise ValueError("Selection exceeds the 32 MiB clipboard limit")
    return content


def decode_selection(content):
    if len(content) > MAX_CLIPBOARD_BYTES:
        raise ValueError("Clipboard exceeds the 32 MiB limit")
    try:
        data = json.loads(content)
        if (
            not isinstance(data, dict)
            or (
                set(data) != {"format", "version", "steps"}
                if data.get("version") == 1
                else set(data) != {"format", "version", "steps", "groups"}
            )
            or data["format"] != "moonlight-selection"
            or type(data["version"]) is not int
            or data["version"] not in (1, 2)
            or not isinstance(data["steps"], list)
            or not 0 < len(data["steps"]) <= MAX_STEPS
        ):
            raise ValueError("Clipboard does not contain Moonlight actions")
        steps = [Step.from_dict(s) for s in data["steps"]]
        groups = data.get("groups", {})
        Script(steps=steps, groups=groups).validate()
        return steps, groups
    except (TypeError, RecursionError) as exc:
        raise ValueError("Invalid action clipboard") from exc


def decode_steps(content):
    return decode_selection(content)[0]


def clone_selection(steps, groups):
    identities = {step.group_id for step in steps if step.group_id}
    mapping = {key: uuid4().hex for key in identities}
    return (
        [replace(step, group_id=mapping.get(step.group_id, "")) for step in steps],
        {mapping[key]: dict(groups[key]) for key in identities},
    )


def randomize_steps(steps, rows, percent):
    number(percent, "Variation (%)", 0, 100)
    result = list(steps)
    for row in rows:
        step = result[row]
        if step.action == "note":
            continue
        result[row] = replace(
            step,
            delay_ms=step.delay_ms * (1 - percent / 100),
            delay_max_ms=min(3_600_000, step.delay_ms * (1 + percent / 100)),
        )
    return result
