"""Explain detected Linux capabilities without initiating input or permission UI."""

import json
import threading

from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QTextEdit, QVBoxLayout

from .compatibility import environment_report, feature_summary, session_type
from .portal_probe import probe
from .widgets import button, label


class CompatibilityDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle("Linux compatibility · Automater")
        self.resize(650, 580)
        self.generation = 0
        self.report = environment_report()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(label("Your Linux setup", "heading"))
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlainText(feature_summary(self.report))
        layout.addWidget(self.details, 1)
        self.status = label(
            "Feature availability is detected, not proof of acceptance by a specific game."
        )
        layout.addWidget(self.status)
        self.check = button("Check pointer portal", self.check_portal, glyph="refresh")
        self.check.setEnabled(session_type() == "wayland")
        self.check.setToolTip(
            "Read interface properties only. No permission request or screen capture is started."
        )
        actions = QHBoxLayout()
        actions.addWidget(self.check)
        actions.addWidget(button("Copy report", self.copy, "ghost", glyph="copy"))
        actions.addStretch()
        actions.addWidget(button("Done", self.accept, "primary", glyph="check"))
        layout.addLayout(actions)
        window.bridge.compatibility_ready.connect(self.portal_checked)

    def copy(self):
        QApplication.clipboard().setText(json.dumps(self.report, indent=2))
        self.status.setText(
            "Compatibility report copied. It includes desktop/runtime details, not recordings."
        )

    def check_portal(self):
        self.generation += 1
        generation = self.generation
        self.check.setEnabled(False)
        self.status.setText("Reading portal capabilities… no permission dialog is opened.")
        bridge = self.parent().bridge

        def check():
            report = probe()
            try:
                bridge.compatibility_ready.emit(generation, report)
            except RuntimeError:
                pass

        threading.Thread(target=check, daemon=True).start()

    def portal_checked(self, generation, result):
        if generation != self.generation:
            return
        self.report["pointer_portal"] = result
        self.status.setText(result["message"])
        self.check.setEnabled(True)


class CompatibilityMixin:
    def show_compatibility(self):
        if self.compatibility_dialog is None:
            self.compatibility_dialog = CompatibilityDialog(self)
        self.compatibility_dialog.show()
        self.compatibility_dialog.raise_()
