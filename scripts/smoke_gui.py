"""Input-free native GUI smoke check for CI's private display servers."""

import json
import tempfile

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from moonlight_studio import window

app = QApplication([])
window.devices = lambda: []
window.x11.windows = lambda: []
with tempfile.TemporaryDirectory(prefix="moonlight-native-smoke-") as folder:
    win = window.MainWindow(folder, demo=True)
    win.show()
    win.apply_appearance("daylight")
    outcome = {}

    def finish():
        outcome.update(
            platform=app.platformName(), visible=win.isVisible(), rendered=not win.grab().isNull()
        )
        win.close()
        app.quit()

    QTimer.singleShot(200, finish)
    app.exec()
    assert outcome["visible"] and outcome["rendered"], outcome
    print(json.dumps(outcome))
