from PySide6.QtCore import QLocale, Qt
from test_gui import clean, window

from automater.actions import create_action
from automater.inspector import milliseconds
from automater.key_picker import KeyPicker
from automater.models import Script


def test_time_fields_show_clean_values_without_losing_sample_precision(qtbot):
    spin = milliseconds()
    qtbot.addWidget(spin)
    spin.setLocale(QLocale("en_US"))
    for value, display in (
        (0, "0 ms"),
        (650, "650 ms"),
        (0.125, "0.125 ms"),
        (1_000_000, "1000000 ms"),
    ):
        spin.setValue(value)
        assert spin.text() == display
        assert spin.value() == value
    spin.lineEdit().setText("0.375 ms")
    spin.interpretText()
    assert spin.value() == 0.375
    spin.setLocale(QLocale("de_DE"))
    assert spin.text() == "0,375 ms"
    spin.lineEdit().setText("0,625 ms")
    spin.interpretText()
    assert spin.value() == 0.625


def test_friendly_key_labels_keep_raw_code_input(qtbot):
    picker = KeyPicker()
    qtbot.addWidget(picker)
    picker.set_code("KEY_W")
    assert picker.currentText() == "W" and picker.code() == "KEY_W"
    picker.setEditText("KEY_F24")
    assert picker.code() == "KEY_F24"


def test_existing_random_timing_is_visible_and_survives_collapsing_options(
    qtbot, tmp_path, monkeypatch
):
    win = window(qtbot, tmp_path, monkeypatch)
    steps = create_action(0, "KEY_W", duration=650, maximum=900)
    win.load_script(Script(steps=steps))
    win.workflow.canvas.choose_indices({0})
    inspector = win.action_inspector
    assert inspector.more_btn.isChecked() and inspector.advanced.isVisible()
    assert inspector.duration_max.value() == 900
    qtbot.mouseClick(inspector.more_btn, Qt.LeftButton)
    assert not inspector.advanced.isVisible()
    qtbot.mouseClick(inspector.apply_btn, Qt.LeftButton)
    assert win.model.steps == steps
    inspector.duration.setValue(0.125)
    inspector.apply()
    assert win.model.steps[1].delay_ms == 0.125
    assert win.model.steps[1].delay_max_ms == 900
    clean(win)
