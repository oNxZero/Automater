"""A complete example built with the real editor, ending in a verified Test run."""

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .actions import create_action
from .models import Script
from .widgets import button, label

LESSONS = (
    (
        "Build your first workflow",
        "We'll hold Space, wait a moment, then tap E. You'll build it in a new tab and run it in Test mode.",
    ),
    (
        "1 · Add a Space hold",
        "Click Add action → Hold key / button. Choose Space and Add action. We'll adjust its duration next.",
    ),
    (
        "2 · Set the hold duration",
        "Set Hold for to 500 ms, then Apply changes. This keeps Space held for half a second.",
    ),
    (
        "3 · Add a pause",
        "Click Add action → Timer / wait. Set Timer duration to 300 ms and Add action.",
    ),
    (
        "4 · Add the final key",
        "Click Add action → Hold key / button. Choose E, set Hold for to 100 ms, then Add action.",
    ),
    (
        "5 · Run your workflow",
        "Test mode is on. Click Run and watch all three actions play in order. F12 stops the preview.",
    ),
    (
        "Congratulations!",
        "You built a complete workflow and ran it successfully in Test mode. Your example stays in its tab as a reference.",
    ),
)


def example_steps():
    return (
        create_action(0, "KEY_SPACE", duration=500)
        + create_action(2, duration=300)
        + create_action(0, "KEY_E", duration=100)
    )


def signature(steps):
    return tuple((s.action, s.code, s.delay_ms, s.delay_max_ms, s.x, s.y, s.enabled) for s in steps)


class ControlOutline(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.holes = []

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(theme.paint_color(theme.ACCENT), 1.5))
        painter.setBrush(Qt.NoBrush)
        for rect in self.holes:
            painter.drawRoundedRect(QRectF(rect), 9, 9)


class GuideCard(QFrame):
    def __init__(self, guide, parent):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedWidth(350)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(11)
        header = QHBoxLayout()
        self.counter = label("YOUR FIRST WORKFLOW", "eyebrow")
        self.counter.setWordWrap(False)
        header.addWidget(self.counter)
        header.addStretch()
        self.skip_btn = button("Skip", guide.reject, "ghost")
        self.skip_btn.setStyleSheet("padding: 2px 0; min-height: 16px; font-size: 11px;")
        header.addWidget(self.skip_btn)
        layout.addLayout(header)
        self.progress = QProgressBar()
        self.progress.setRange(0, 5)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Example guide progress")
        layout.addWidget(self.progress)
        self.heading = label("", "heading")
        self.description = label("", "body")
        self.goal = label("Space 500 ms → Wait 300 ms → E 100 ms")
        self.status = label("")
        for widget in (self.heading, self.description, self.goal, self.status):
            layout.addWidget(widget)
        footer = QHBoxLayout()
        self.back_btn = button("Back", lambda: guide.go(-1), "ghost", glyph="left")
        self.keep_btn = button("Keep editing", guide.reject, "ghost")
        footer.addWidget(self.back_btn)
        footer.addWidget(self.keep_btn)
        footer.addStretch()
        self.next_btn = button("Start example", lambda: guide.go(1), "primary", glyph="right")
        footer.addWidget(self.next_btn)
        layout.addLayout(footer)

    def fit_content(self):
        for widget in (self.heading, self.description, self.goal, self.status):
            widget.setFixedHeight(widget.heightForWidth(self.width() - 36))
        self.setFixedHeight(self.layout().sizeHint().height())

    def set_status(self, text):
        if self.status.text() != text:
            self.status.setText(text)
            self.fit_content()


class TutorialTour(QObject):
    finished = Signal(int)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.root = window.centralWidget()
        self.document_id = None
        self.step = 0
        self.closing = False
        self.succeeded = False
        self.expected_replay = None
        self.expected = signature(example_steps())
        self.shade = ControlOutline(self.root)
        self.card = GuideCard(self, self.root)
        window.model.inputChanged.connect(self.actions_changed)
        self.poll = QTimer(self)
        self.poll.setInterval(60)
        self.poll.timeout.connect(self.tick)

    def show(self):
        QApplication.instance().installEventFilter(self)
        self.render_step()
        self.poll.start()

    def raise_(self):
        self.shade.show()
        self.shade.raise_()
        self.card.show()
        self.card.raise_()

    def activateWindow(self):
        self.card.next_btn.setFocus()

    def actions_changed(self):
        self.expected_replay = None

    def start_example(self):
        if self.document_id is None:
            if not self.window.load_script(Script("My first workflow")):
                self.card.set_status("Finish your current edit, then start the example.")
                return False
            self.document_id = self.window.active_document_id
            win = self.window
            win.test_mode.setChecked(True)
            win.speed.setValue(1)
            win.repeats.setValue(1)
            win.countdown.setValue(0)
            win.mode.setCurrentIndex(0)
            win.start_enabled.setChecked(False)
        self.step = 1
        self.render_step()
        return True

    def complete(self, step):
        steps = self.window.model.steps
        actual = signature(steps)
        if step == 1:
            return (
                len(steps) >= 2
                and actual[0] == self.expected[0]
                and actual[1][:2] == self.expected[1][:2]
                and actual[1][3:] == self.expected[1][3:]
            )
        if step == 2:
            return actual[:2] == self.expected[:2]
        if step == 3:
            return actual[:3] == self.expected[:3]
        if step == 4:
            return actual == self.expected
        return False

    def render_step(self):
        win = self.window
        title, description = LESSONS[self.step]
        self.card.counter.setText(
            "EXAMPLE COMPLETE"
            if self.step == 6
            else f"STEP {self.step} OF 5"
            if self.step
            else "YOUR FIRST WORKFLOW"
        )
        self.card.progress.setValue(min(5, max(0, self.step - 1)))
        self.card.heading.setText(title)
        self.card.description.setText(description)
        self.card.skip_btn.setText("Close" if self.step == 6 else "Skip")
        self.card.back_btn.setVisible(1 < self.step < 6)
        self.card.keep_btn.setVisible(self.step == 6)
        self.card.next_btn.setVisible(self.step != 5)
        self.card.next_btn.setText(
            "Start example" if self.step == 0 else "Create my own" if self.step == 6 else "Next"
        )
        if self.step == 0:
            self.card.set_status("About two minutes. Your existing workflows are kept.")
        elif self.step == 6:
            self.card.set_status("✓ All 3 actions completed · No real input sent")
        if self.step in (1, 2, 3, 4, 5):
            win.navigate(0)
            if self.step in (1, 3, 4):
                win.hide_inspector()
                if self.step in (3, 4) and win.blocks:
                    index = min(self.step - 3, len(win.blocks) - 1)
                    win.workflow.canvas.choose_indices({index}, emit=False)
                    win.select_blocks([win.blocks[index]], open_inspector=False)
            elif self.step == 2:
                if win.blocks:
                    win.workflow.canvas.choose_indices({0})
                win.show_inspector(0)
                QTimer.singleShot(80, self, self.reveal_timing)
            else:
                win.test_mode.setChecked(True)
                win.show_inspector(1)
                QTimer.singleShot(80, self, self.reveal_test_mode)
        self.refresh_status()
        self.card.fit_content()
        self.position()
        self.raise_()

    def refresh_status(self):
        ready = self.step in (0, 6) or self.complete(self.step)
        self.card.next_btn.setEnabled(ready and not self.window.busy)
        self.card.back_btn.setEnabled(not self.window.busy)
        messages = {
            1: ("Choose Space and add the Hold to continue.", "✓ Space hold added. Choose Next."),
            2: ("Set Hold for to 500 ms and apply it.", "✓ Hold duration is 500 ms. Choose Next."),
            3: ("Add a 300 ms Timer after the Space hold.", "✓ Pause added. Choose Next."),
            4: ("Add a 100 ms E hold after the Timer.", "✓ Your three-action workflow is ready."),
        }
        if self.step in messages:
            self.card.set_status(messages[self.step][ready])
        elif self.step == 5:
            replay = getattr(self.window, "replay", None)
            trace = self.window.last_run
            if self.window.busy:
                self.card.set_status("Preview running… watch the highlight move.")
            elif (
                replay is self.expected_replay
                and trace
                and trace["outcome"] in ("stopped", "failed")
            ):
                self.card.set_status(
                    "Preview stopped. Click Run to try again."
                    if trace["outcome"] == "stopped"
                    else "Preview failed. Check the message below, then retry."
                )
            elif signature(self.window.model.steps) != self.expected:
                self.card.set_status("The example changed. Use Back to check the three actions.")
            else:
                self.card.set_status("Click Run · F7. You'll finish after a successful preview.")

    def go(self, direction):
        if self.closing or self.window.busy:
            return
        if self.step == 0:
            self.start_example()
            return
        if self.step == 6:
            win = self.window
            self.reject()
            win.new_script()
            return
        if direction > 0 and not self.complete(self.step):
            return
        self.step = max(1, min(5, self.step + direction))
        self.render_step()

    def setup_action_dialog(self, dialog):
        if self.step not in (1, 3, 4):
            return
        instructions = {
            1: "Choose Hold key / button and Space. Leave Delay before at 0 ms, then Add action.",
            3: "Choose Timer / wait. Set Timer duration to 300 ms, then Add action.",
            4: "Choose Hold key / button and E. Set Hold for to 100 ms and Delay before to 0 ms.",
        }
        banner = QFrame()
        banner.setObjectName("notice")
        layout = QVBoxLayout(banner)
        layout.setContentsMargins(12, 9, 12, 9)
        row = QHBoxLayout()
        row.addWidget(label(f"TUTORIAL · STEP {self.step} OF 5", "eyebrow"))
        row.addStretch()

        def skip():
            dialog.reject()
            self.reject()

        row.addWidget(button("Skip", skip, "ghost"))
        layout.addLayout(row)
        layout.addWidget(label(instructions[self.step], "body"))
        dialog.layout().insertWidget(1, banner)

    def playback_started(self, replay, script):
        self.expected_replay = (
            replay
            if signature(script.steps) == self.expected
            and self.window.active_document_id == self.document_id
            else None
        )

    def widget_rect(self, widget):
        if not widget.isVisible():
            return QRect()
        visible = widget.visibleRegion().boundingRect()
        if visible.isEmpty():
            return QRect()
        rect = QRect(self.root.mapFromGlobal(widget.mapToGlobal(visible.topLeft())), visible.size())
        return rect.adjusted(-5, -5, 5, 5).intersected(self.root.rect().adjusted(4, 4, -4, -4))

    def targets(self):
        win = self.window
        widgets = (
            [win.action_inspector.duration, win.action_inspector.apply_btn]
            if self.step == 2
            else [win.test_mode, win.play_btn]
            if self.step == 5
            else [win.add_btn]
            if self.step < 5
            else []
        )
        return [rect for widget in widgets if not (rect := self.widget_rect(widget)).isEmpty()]

    def position(self):
        self.shade.setGeometry(self.root.rect())
        holes = self.targets()
        self.shade.holes = holes
        self.shade.update()
        width, height = self.card.width(), self.card.height()
        if self.step == 6:
            self.card.move(
                (self.root.width() - width) // 2, max(16, (self.root.height() - height) // 2)
            )
            return
        anchor = holes[0] if holes else QRect(self.root.width() - 60, 90, 20, 30)
        candidates = []
        if self.step in (2, 5):
            candidates.append(
                QPoint(
                    self.widget_rect(self.window.inspector_panel).left() - width - 12, anchor.top()
                )
            )
        candidates += [
            QPoint(anchor.left() - width - 12, anchor.top()),
            QPoint(anchor.right() - width, anchor.bottom() + 12),
            QPoint(anchor.left(), anchor.top() - height - 12),
            QPoint(24, self.root.height() - height - 90),
        ]
        obstacles = holes + (
            [self.widget_rect(self.window.inspector_panel)] if self.step in (2, 5) else []
        )
        choices = []
        available = self.root.rect().adjusted(16, 16, -16, -16)
        for index, point in enumerate(candidates):
            box = QRect(
                max(available.left(), min(point.x(), available.right() - width)),
                max(available.top(), min(point.y(), available.bottom() - height)),
                width,
                height,
            )
            overlap = sum(
                (intersection := box.intersected(hole)).width() * intersection.height()
                for hole in obstacles
                if box.intersects(hole)
            )
            choices.append((overlap, index, box))
        self.card.move(min(choices, key=lambda value: value[:2])[2].topLeft())

    def reveal_timing(self):
        if not self.closing and self.step == 2:
            self.window.action_inspector.findChild(QScrollArea).ensureWidgetVisible(
                self.window.action_inspector.duration, 6, 6
            )

    def reveal_test_mode(self):
        if self.closing or self.step != 5:
            return
        widget = self.window.test_mode
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(widget, 6, 6)
                break
            parent = parent.parentWidget()

    def tick(self):
        win = self.window
        if self.closing:
            if not win.busy:
                self.finish()
            return
        if self.document_id is not None and win.active_document_id != self.document_id:
            self.reject()
            return
        if (
            QApplication.activeModalWidget() is not None
            or QApplication.activePopupWidget() is not None
        ):
            self.card.hide()
            self.shade.hide()
            return
        trace = win.last_run
        if (
            self.step not in (0, 6)
            and self.expected_replay is not None
            and win.replay is self.expected_replay
            and not win.busy
            and trace
            and trace["outcome"] == "finished"
            and trace["completed_events"] == trace["enabled_events"] == 5
            and trace["loop"] == 1
            and signature(win.model.steps) == self.expected
        ):
            self.succeeded = True
            self.step = 6
            self.render_step()
        self.refresh_status()
        self.position()
        self.raise_()

    def cancel_preview(self):
        if self.document_id == self.window.active_document_id and self.window.busy:
            self.window.stop()

    def reject(self):
        if self.closing:
            return
        self.closing = True
        self.shade.hide()
        self.card.hide()
        self.cancel_preview()
        if not self.window.busy:
            self.finish()

    def finish(self):
        self.poll.stop()
        QApplication.instance().removeEventFilter(self)
        win = self.window
        if (
            self.document_id is not None
            and win.active_document_id == self.document_id
            and not win.model.steps
        ):
            win.close_document(win.document_tabs.currentIndex())
        self.shade.deleteLater()
        self.card.deleteLater()
        self.finished.emit(0)
        self.deleteLater()

    def eventFilter(self, obj, event):
        if (
            event.type() == QEvent.KeyPress
            and event.key() == Qt.Key_Escape
            and QApplication.activeModalWidget() is None
            and QApplication.activePopupWidget() is None
            and isinstance(obj, QWidget)
            and obj.window() is self.window
        ):
            self.reject()
            return True
        return super().eventFilter(obj, event)


class TutorialMixin:
    def offer_tutorial(self):
        if self.first_launch and not self.demo and not self.preferences.tutorial_seen:
            self.show_tutorial()

    def show_tutorial(self):
        if self.busy:
            return
        if self.tutorial_dialog is not None:
            self.tutorial_dialog.raise_()
            self.tutorial_dialog.activateWindow()
            return
        guide = TutorialTour(self)
        self.tutorial_dialog = guide

        def dismissed(_result):
            self.preferences.tutorial_seen = True
            self.tutorial_dialog = None
            self.save_preferences()

        guide.finished.connect(dismissed)
        guide.show()
