from dataclasses import replace

import pytest
from test_engine import Backend
from test_gui import clean, window

from moonlight_studio.actions import clone_selection, decode_selection, encode_steps
from moonlight_studio.engine import PlaybackOptions, Replay
from moonlight_studio.models import Script, Step
from moonlight_studio.storage import load, save


def annotated():
    return Script(
        "Documented routine",
        steps=[
            Step(
                0,
                "note",
                title="Open application",
                text="Use the same screen layout.",
                group_id="open",
            ),
            Step(0, "key_down", "KEY_E", group_id="open"),
            Step(10, "key_up", "KEY_E", group_id="open"),
            Step(0, "note", title="Next", text="Then close the app."),
        ],
        groups={"open": {"name": "Open program", "color": "#83b8f2"}},
    )


def test_notes_groups_round_trip_and_old_workflows_stay_compatible(tmp_path):
    script = annotated()
    path = tmp_path / "annotated.json"
    save(script, path)
    restored = load(path)
    assert restored.to_dict() == script.to_dict()
    assert restored.version == 3 and restored.duration_ms == 10
    plain = Script(steps=[Step(20)])
    assert plain.to_dict()["version"] == 1
    assert "groups" not in plain.to_dict()
    assert "group_id" not in plain.to_dict()["steps"][0]


@pytest.mark.parametrize(
    "change",
    [
        {"groups": []},
        {"groups": {"open": {"name": "", "color": "#83b8f2"}}},
        {"groups": {"open": {"name": "Group", "color": "red"}}},
        {"groups": {"open": {"name": "Group", "color": "#83b8f2", "extra": True}}},
        {"groups": {}},
    ],
)
def test_invalid_or_missing_group_metadata_is_rejected(change):
    data = annotated().to_dict()
    data.update(change)
    with pytest.raises(ValueError):
        Script.from_dict(data)


def test_note_limits_and_visual_only_timing_are_validated():
    for fields in ({"delay_ms": 1}, {"delay_max_ms": 1}, {"text": "x" * 4001}):
        with pytest.raises(ValueError):
            replace(Step(0, "note"), **fields)


def test_replay_skips_notes_and_keeps_input_rows_and_counts():
    backend = Backend()
    replay = Replay(lambda: backend)
    replay.start(annotated(), PlaybackOptions(countdown=0))
    assert replay.join()
    assert [s.action for s in backend.events] == ["key_down", "key_up"]
    assert replay.timeline["enabled_events"] == replay.timeline["completed_events"] == 2
    assert replay.timeline["completed_row"] == 2
    with pytest.raises(ValueError):
        replay.start(Script(steps=[Step(0, "note", text="Only documentation")]))


def test_grouped_clipboard_clones_identities_and_keeps_notes_and_input():
    source = annotated()
    content = encode_steps(source.steps, source.groups)
    steps, groups = decode_selection(content)
    assert steps == source.steps and groups == source.groups
    copies, copied_groups = clone_selection(steps, groups)
    assert set(copied_groups).isdisjoint(groups)
    assert [s.action for s in copies] == [s.action for s in steps]
    assert copies[0].text == steps[0].text
    assert copies[1].group_id == copies[0].group_id
    assert Script(steps=copies, groups=copied_groups).validate()


def test_group_rename_remove_and_undo_are_atomic(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    before = list(win.model.steps)
    win.workflow.canvas.choose_indices({0, 2})
    win.group_selection("Enter text", "#75d6c0")
    assert len(win.model.groups) == 1
    assert (
        len(win.workflow.canvas.group_items) == 2
    )  # Two spans; the unselected timer stays outside.
    grouped = win.script().to_dict()
    win.group_selection("Close program", "#83b8f2")
    assert next(iter(win.model.groups.values()))["name"] == "Close program"
    win.undo.undo()
    assert win.script().to_dict() == grouped
    win.select_group(next(iter(win.model.groups)))
    win.ungroup_selection()
    assert not win.model.groups
    win.undo.undo()
    assert win.script().to_dict() == grouped
    win.undo.undo()
    assert win.model.steps == before and not win.model.groups
    clean(win)


def test_note_inspector_edits_text_without_input_or_delay(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.insert_steps([Step(0, "note", title="Explanation", text="Original")], row=0)
    ins = win.action_inspector
    assert ins.note_fields.isVisible()
    assert not ins.rerecord_btn.isVisible()
    ins.note_title.setText("Enter text")
    ins.note_text.setPlainText("<b>Literal text</b>\nUse the correct keyboard layout.")
    ins.apply()
    assert win.model.steps[0].title == "Enter text"
    assert win.model.steps[0].text.startswith("<b>")
    assert win.model.steps[0].delay_ms == 0
    win.undo.undo()
    assert win.model.steps[0].text == "Original"
    clean(win)


def test_grouped_actions_paste_into_another_workflow_with_metadata(qtbot, tmp_path, monkeypatch):
    win = window(qtbot, tmp_path, monkeypatch)
    win.workflow.canvas.choose_indices({0})
    win.group_selection("Launch")
    original_ids = set(win.model.groups)
    win.copy_selection()
    win.new_script()
    win.paste_selection()
    assert len(win.model.steps) == 2 and len(win.model.groups) == 1
    assert original_ids.isdisjoint(win.model.groups)
    assert win.script().validate()
    win.undo.undo()
    assert not win.model.steps and not win.model.groups
    clean(win)


def test_group_header_selects_members_and_preserves_input_data(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QPointF, Qt

    win = window(qtbot, tmp_path, monkeypatch)
    win.workflow.canvas.choose_indices({0, 2})
    win.group_selection("Open program")
    before = win.script().to_dict()
    canvas = win.workflow.canvas
    win.hide_inspector()
    canvas.choose_indices(set())
    qtbot.wait(30)
    frame = next(iter(canvas.group_items.values()))
    position = canvas.mapFromScene(frame.pos() + QPointF(30, 12))
    qtbot.mouseClick(canvas.viewport(), Qt.LeftButton, pos=position)
    assert canvas.selected_indices == {0, 2}
    assert win.script().to_dict() == before
    clean(win)
