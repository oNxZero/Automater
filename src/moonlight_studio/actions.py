"""Data-only authoring and bounded selection clipboard helpers."""

import json
from dataclasses import asdict, replace

from .models import KEY_CODES, MAX_STEPS, Step, number

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


def encode_steps(steps):
    if not steps or len(steps) > MAX_STEPS:
        raise ValueError("Choose between 1 and 200,000 events to copy")
    content = json.dumps(
        {"format": "moonlight-selection", "version": 1, "steps": [asdict(s) for s in steps]},
        allow_nan=False,
    ).encode()
    if len(content) > MAX_CLIPBOARD_BYTES:
        raise ValueError("Selection exceeds the 32 MiB clipboard limit")
    return content


def decode_steps(content):
    if len(content) > MAX_CLIPBOARD_BYTES:
        raise ValueError("Clipboard exceeds the 32 MiB limit")
    try:
        data = json.loads(content)
        if (
            not isinstance(data, dict)
            or set(data) != {"format", "version", "steps"}
            or data["format"] != "moonlight-selection"
            or type(data["version"]) is not int
            or data["version"] != 1
            or not isinstance(data["steps"], list)
            or not 0 < len(data["steps"]) <= MAX_STEPS
        ):
            raise ValueError("Clipboard does not contain Moonlight actions")
        return [Step.from_dict(s) for s in data["steps"]]
    except (TypeError, RecursionError) as exc:
        raise ValueError("Invalid action clipboard") from exc


def randomize_steps(steps, rows, percent):
    number(percent, "Variation (%)", 0, 100)
    result = list(steps)
    for row in rows:
        step = result[row]
        result[row] = replace(
            step,
            delay_ms=step.delay_ms * (1 - percent / 100),
            delay_max_ms=min(3_600_000, step.delay_ms * (1 + percent / 100)),
        )
    return result
