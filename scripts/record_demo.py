"""Capture the real Automater UI in input-free Test mode; encode with FFmpeg.

QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/record_demo.py
Only synthetic workflows and an isolated temporary config are used.
"""

import argparse
import shutil
import subprocess
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from automater import window
from automater.actions import create_action
from automater.desktop import APP_ID
from automater.dialogs import SaveChangesDialog
from automater.models import Script


def routine():
    groups = {
        "move": dict(
            name="01 · Move into position",
            color="#83b8f2",
            notes="Choose your starting point, then move into position.",
        ),
        "interact": dict(
            name="02 · Interact",
            color="#b5a4fa",
            notes="Open the menu, choose an item and confirm.",
        ),
        "finish": dict(
            name="03 · Finish & repeat",
            color="#75d6c0",
            notes="Return to the start. Set repetitions in Run settings.",
        ),
    }
    actions = [
        (0, "KEY_W", 900),
        (3, None, 0),
        (2, None, 700),
        (0, "KEY_E", 500),
        (0, "KEY_I", 450),
        (2, None, 650),
        (1, "BTN_LEFT", 350),
        (0, "KEY_ENTER", 450),
        (0, "KEY_ESC", 350),
        (0, "KEY_S", 900),
        (2, None, 700),
        (0, "KEY_E", 450),
    ]
    steps = []
    for index, (kind, code, duration) in enumerate(actions):
        identity = ("move", "interact", "finish")[index // 4]
        steps.extend(
            replace(step, group_id=identity)
            for step in create_action(kind, code, duration=duration)
        )
    return Script("Gather & return", "Demo · Test mode sends no input", steps, groups=groups)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs/workflow-demo.gif",
    )
    args = parser.parse_args()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        parser.error("FFmpeg is needed to encode the demo; it is not an app runtime dependency")
    app = QApplication([APP_ID])
    window.devices = lambda: []
    window.x11.windows = lambda: []
    SaveChangesDialog.ask = lambda *args: "discard"
    with tempfile.TemporaryDirectory(prefix="automater-demo-") as folder:
        temporary = Path(folder)
        win = window.MainWindow(temporary / "config", demo=True)
        try:
            win.resize(1280, 840)
            win.load_script(routine())
            win.test_mode.setChecked(True)
            win.start_enabled.setChecked(False)
            win.countdown.setValue(1)
            win.speed.setValue(1)
            win.workflow.layout_choice.setCurrentIndex(2)
            win.workflow.follow_btn.setChecked(True)
            win.hide_inspector()
            win.show()
            win.workflow.canvas.choose_indices(set())
            QTest.qWait(200)
            win.workflow.canvas.fit()
            started = time.monotonic()
            launched = False
            finished = None
            frame = 0
            while time.monotonic() - started < 18:
                elapsed = time.monotonic() - started
                if not launched and elapsed >= 0.65:
                    assert win.test_mode.isChecked()
                    win.toggle_play()
                    assert win.busy, win.status.text()
                    launched = True
                if launched and not win.busy:
                    if finished is None:
                        finished = elapsed
                    if elapsed - finished > 1.5:
                        break
                assert win.grab().save(str(temporary / f"frame-{frame:04d}.png"))
                frame += 1
                QTest.qWait(max(1, round((started + frame / 20 - time.monotonic()) * 1000)))
            assert finished is not None, "Demo playback failed to finish"
            assert win.last_run["outcome"] == "finished", win.last_run
        finally:
            win.stop()
            win.saved_snapshot = win.script().to_dict()
            win.close()
            app.processEvents()
        encoded = temporary / "workflow-demo.gif"
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-framerate",
                "20",
                "-i",
                str(temporary / "frame-%04d.png"),
                "-filter_complex",
                "scale=1152:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=192:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle",
                "-loop",
                "0",
                "-y",
                str(encoded),
            ],
            check=True,
            timeout=90,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(encoded, args.output)
        print(
            f"Saved {args.output}: {frame} frames, {args.output.stat().st_size / 1024 / 1024:.2f} MiB"
        )


if __name__ == "__main__":
    main()
