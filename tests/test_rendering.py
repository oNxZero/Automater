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
