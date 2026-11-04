import json

import pytest

from automater.preferences import Preferences


def test_preferences_round_trip_and_private_file(tmp_path):
    path = tmp_path / "preferences.json"
    prefs = Preferences(
        device_ids=["usb-keyboard"],
        speed=1.7,
        repeats=4,
        capture_motion=False,
        append_recording=True,
    )
    prefs.save(path)
    assert Preferences.load(path) == prefs
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "fields",
    [
        {"speed": 0},
        {"speed": float("nan")},
        {"repeats": True},
        {"countdown": 1.5},
        {"device_ids": "event1"},
        {"device_ids": [1]},
        {"append_recording": "yes"},
        {"capture_keys": None},
        {"script_directory": "relative/folder"},
        {"script_directory": True},
        {"script_directory": "/invalid\x00folder"},
    ],
)
def test_invalid_preferences_rejected(tmp_path, fields):
    path = tmp_path / "preferences.json"
    path.write_text(json.dumps({"version": 1, **fields}))
    with pytest.raises(ValueError):
        Preferences.load(path)


def test_no_devices_selected_differs_from_recommended_defaults(tmp_path):
    path = tmp_path / "preferences.json"
    assert Preferences.load(path).device_ids is None
    Preferences(device_ids=[]).save(path)
    assert Preferences.load(path).device_ids == []


def test_deeply_nested_corrupt_preferences_raise_validation_error(tmp_path):
    path = tmp_path / "preferences.json"
    path.write_text("[" * 5000 + "]" * 5000)
    with pytest.raises(ValueError):
        Preferences.load(path)
