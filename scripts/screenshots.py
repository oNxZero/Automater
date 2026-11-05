"""Render documentation from the actual Qt UI using synthetic workflows only.

Run with QT_QPA_PLATFORM=offscreen. No physical capture, portals or input output.
"""

import tempfile
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from automater import window
from automater.actions import create_action
from automater.desktop import APP_ID
from automater.dialogs import SaveChangesDialog
from automater.models import Script
from automater.open_windows import DesktopWindow
from automater.overlay import PointerOverlay
from automater.window_picker import WindowPicker

OUTPUT = Path(__file__).resolve().parents[1] / "docs"
app = QApplication([APP_ID])
window.devices = lambda: []
window.x11.windows = lambda: []
SaveChangesDialog.ask = lambda *args: "discard"


def capture(name, widget):
    QTest.qWait(140)
    assert widget.grab().save(str(OUTPUT / f"{name}.png"))


def routine():
    groups = {
        "move": dict(
            name="01 · Move into position",
            color="#83b8f2",
            notes="Start from the same spot. Hold W, turn, then pause before interacting.",
        ),
        "interact": dict(
            name="02 · Interact",
            color="#b5a4fa",
            notes="Open the menu, select an item, then confirm. Adjust each hold if your game needs more time.",
        ),
        "finish": dict(
            name="03 · Finish & repeat",
            color="#75d6c0",
            notes="Close the menu and return to the start. Set repetitions in Run settings.",
        ),
    }
    actions = [
        (0, "KEY_W", 650),
        (3, None, 0),
        (2, None, 250),
        (0, "KEY_E", 80),
        (0, "KEY_I", 80),
        (2, None, 300),
        (1, "BTN_LEFT", 90),
        (0, "KEY_ENTER", 80),
        (0, "KEY_ESC", 80),
        (0, "KEY_S", 650),
        (2, None, 400),
        (0, "KEY_E", 80),
    ]
    steps = []
    for index, (kind, code, duration) in enumerate(actions):
        identity = ("move", "interact", "finish")[index // 4]
        steps.extend(
            replace(step, group_id=identity)
            for step in create_action(kind, code, duration=duration)
        )
    return Script(
        "Gather & return",
        "A synthetic example. Preview with Test mode before sending input.",
        steps,
        groups=groups,
    )


with tempfile.TemporaryDirectory(prefix="automater-docs-") as folder:
    win = window.MainWindow(folder, demo=True)
    win.resize(1440, 960)
    win.show()
    win.load_script(routine())
    win.workflow.layout_choice.setCurrentIndex(2)
    win.hide_inspector()
    win.navigate(0)
    win.workflow.canvas.choose_indices(set())
    QTest.qWait(150)
    win.workflow.canvas.fit()
    capture("editor", win)
    win.show_appearance()
    capture("themes", win.appearance_dialog)
    win.appearance_dialog.hide()
    win.apply_appearance("daylight")
    capture("daylight", win)
    win.apply_appearance("automater")
    win.navigate(0, 1)
    capture("events", win)
    win.show_inspector(1)
    capture("run-settings", win)
    win.show_inspector(2)
    capture("start-controls", win)
    win.navigate(0)
    win.workflow.canvas.choose_indices({0, 3})
    capture("batch-edit", win)
    win.inspect_group("move")
    capture("group-notes", win)
    win.hide_inspector()
    win.workflow.canvas.choose_indices(set())
    win.record_preview.set_snapshot(34, win.model.steps[:8], ["KEY_W"], 2.6)
    win.record_preview.show()
    capture("recording-preview", win)
    win.record_preview.hide()
    win.navigate(2)
    capture("setup", win)
    win.show_inspector(1)
    picker = WindowPicker(win, lambda: None)
    picker.set_windows(
        [
            DesktopWindow("synthetic-1", "Example game · Practice world", 1, ("example.game",)),
            DesktopWindow("synthetic-2", "Text editor · notes.txt", 2, ("example.editor",)),
        ]
    )
    picker.show()
    capture("window-picker", picker)
    picker.close()
    dialog = SaveChangesDialog(win, "Gather & return", count=12)
    dialog.show()
    capture("save-changes", dialog)
    dialog.close()
    win.hide_inspector()
    win.countdown.setValue(0)
    win.speed.setValue(10)
    win.toggle_play()
    while win.busy:
        QTest.qWait(30)
    capture("run-results", win)
    win.show_inspector(1)
    win.mode.setCurrentIndex(2)
    capture("isolated-session", win)
    win.mode.setCurrentIndex(0)
    win.hide_inspector()
    overlay = PointerOverlay(app.primaryScreen(), [QPointF(320, 220), QPointF(510, 380)])
    overlay.show()
    capture("pointer-guide", overlay)
    overlay.close()
    win.saved_snapshot = win.script().to_dict()
    win.close()
    app.processEvents()
