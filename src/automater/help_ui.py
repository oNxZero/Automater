"""A short, offline guide at the point where users create their first routine."""

from PySide6.QtWidgets import QDialog, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from .widgets import button, label


def getting_started(window):
    dialog = QDialog(window)
    dialog.setWindowTitle("Getting started · Automater")
    dialog.resize(600, 610)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.addWidget(label("Your first routine", "heading"))
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    content = QWidget()
    body = QVBoxLayout(content)
    body.setSpacing(12)
    for title, text in (
        (
            "1 · Build or record",
            "Add action inserts after your selection; a + on a connector inserts at that exact point. F6 records and appends to the current workflow. Re-record replaces only the selected consecutive actions.",
        ),
        (
            "2 · Understand the controls",
            "Hold presses and automatically releases a key or button. Press keeps it held; add a Timer and a matching Release. Timers wait without sending input. Movement is relative, in device counts; it is not an absolute screen destination.",
        ),
        (
            "3 · Edit and organize",
            "Ctrl-click or drag a selection box to select actions. Ctrl+D duplicates them after the selection; Ctrl+Z undoes changes. Ctrl+G adds a colored group with notes. Groups are visual categories and do not create loops or branches.",
        ),
        (
            "4 · Choose where to run",
            "Active desktop uses your normal mouse and keyboard. A chosen window is brought forward before playback and must remain focused. Background X11 sends window messages that some games ignore. Separate game session launches an independent Gamescope display; it cannot move a game that is already open.",
        ),
        (
            "5 · Preview, then save",
            "Enable Test mode in Settings before trying a new routine: the real scheduler runs without sending input. F7 runs/stops; F8 pauses; F12 stops or cancels. Save writes a JSON workflow. Recovery protects unfinished edits separately and does not replace your saved file.",
        ),
        (
            "Make it yours",
            "File → Appearance & themes, or Ctrl+, opens the theme gallery. Appearance is local to your installation. F1 on the canvas lists editing shortcuts. Devices explains permissions and capture setup.",
        ),
    ):
        body.addWidget(label(title, "body"))
        body.addWidget(label(text))
    scroll.setWidget(content)
    layout.addWidget(scroll, 1)
    actions = QHBoxLayout()

    def example():
        dialog.accept()
        window.load_example()

    def devices():
        dialog.accept()
        window.navigate(2)

    actions.addWidget(button("Try example · no input", example, glyph="play"))
    actions.addWidget(button("Device setup", devices, "ghost", glyph="settings"))
    actions.addStretch()
    actions.addWidget(button("Done", dialog.accept, "primary", glyph="check"))
    layout.addLayout(actions)
    return dialog
