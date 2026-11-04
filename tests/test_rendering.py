"""Keep native painting crashes visible, including interpreter shutdown failures."""

import os
import subprocess
import sys
import textwrap


def test_repeated_native_painting_exits_cleanly():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                from PySide6.QtWidgets import QApplication
                from PySide6.QtGui import QPainter, QPixmap

                app = QApplication([])
                target, source = QPixmap(100, 100), QPixmap(20, 20)
                target.fill()
                source.fill()
                painter = QPainter(target)
                for _ in range(20_000):
                    painter.drawPixmap(10, 10, source)
                painter.end()
                print('painted')
                """
            ),
        ],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "painted"


def test_copying_actions_exits_cleanly_without_clearing_the_clipboard(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import sys
                from PySide6.QtWidgets import QApplication
                from moonlight_studio import x11
                from moonlight_studio.actions import decode_selection
                from moonlight_studio.dialogs import SaveChangesDialog
                from moonlight_studio.models import Script, Step
                from moonlight_studio.window import MainWindow

                app = QApplication([])
                x11.windows = lambda: []
                SaveChangesDialog.ask = lambda *args: 'discard'
                win = MainWindow(sys.argv[1], demo=True)
                win.load_script(Script(steps=[Step(100)]))
                win.workflow.canvas.choose_indices({0})
                assert win.copy_selection()
                steps, groups = decode_selection(app.clipboard().text().encode())
                assert steps == [Step(100)] and not groups
                win.close()
                app.processEvents()
                assert app.clipboard().text()
                print('copied')
                """
            ),
            str(tmp_path),
        ],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "copied"
