import json

import pytest

from moonlight_studio import storage
from moonlight_studio.models import Script, Step


def test_round_trip_private_atomic_save(tmp_path):
    script = Script(
        "Mining route",
        "Start at base",
        [Step(0, "key_down", "KEY_W"), Step(400, "key_up", "KEY_W")],
    )
    path = tmp_path / "sub" / "route.json"
    storage.save(script, path)
    assert storage.load(path) == script
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "changes",
    [
        {"delay_ms": float("nan")},
        {"delay_ms": float("inf")},
        {"delay_ms": -1},
        {"delay_ms": True},
        {"delay_ms": "100"},
        {"action": "exec"},
        {"action": "key_down", "code": "python"},
        {"x": 1.5},
        {"y": 40000},
        {"enabled": 1},
        {"extra": "field"},
    ],
)
def test_invalid_step_rejected(changes):
    with pytest.raises((ValueError, TypeError)):
        Step.from_dict({**Step().__dict__, **changes})


@pytest.mark.parametrize(
    "data",
    [
        [],
        {},
        {"version": 2, "steps": []},
        {"version": True, "steps": []},
        {"version": 1, "steps": "code"},
        {"version": 1, "steps": [{}], "name": ""},
        {"version": 1, "steps": [], "python": "print(1)"},
    ],
)
def test_bad_scripts(data):
    with pytest.raises(ValueError):
        Script.from_dict(data)


def test_failed_replace_preserves_original(tmp_path, monkeypatch):
    path = tmp_path / "macro.json"
    storage.save(Script("Before"), path)

    def fail(*args):
        raise OSError("Disk failure")

    monkeypatch.setattr(storage.os, "replace", fail)
    with pytest.raises(OSError):
        storage.save(Script("After"), path)
    assert storage.load(path).name == "Before"
    assert list(tmp_path.iterdir()) == [path]


def test_bounded_load(tmp_path, monkeypatch):
    path = tmp_path / "oversized.json"
    path.write_text(json.dumps(Script().to_dict()))
    monkeypatch.setattr(storage, "MAX_BYTES", 5)
    with pytest.raises(ValueError, match="32 MiB"):
        storage.load(path)


def test_warning_and_disabled_timing():
    script = Script(
        steps=[Step(20, "key_up", "KEY_A"), Step(50, "key_down", "KEY_B"), Step(100, enabled=False)]
    )
    assert script.duration_ms == 70
    assert len(script.warnings()) == 2
