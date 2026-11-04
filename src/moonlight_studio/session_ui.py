"""Game-session controls keep process/network work outside the Qt UI thread."""

import threading
import time

from PySide6.QtWidgets import QMessageBox

from .isolated import GameSession, application_command


class SessionMixin:
    def set_session_status(self, text):
        self.session_status.setText(text)
        self.session_dialog_status.setText(text)

    def choose_existing_desktop_window(self):
        self.session_dialog.hide()
        self.mode.setCurrentIndex(0)
        self.choose_open_window()

    def launch_game_session(self):
        if self.session_launching or self.busy:
            return
        if self.game_session.process and self.game_session.process.poll() is None:
            self.show_error("A game session is already open; select its game window below")
            return
        self.game_session.cleanup_finished()
        self.game_session = GameSession()
        self.session_generation += 1
        generation = self.session_generation
        session = self.game_session
        sober = self.session_app.currentIndex() == 0
        custom = self.session_command.text()
        width, height = self.session_size.currentData()
        self.session_launching = True
        self.set_session_status("Starting a separate game display…")
        self.launch_session_btn.setEnabled(False)

        def launch():
            try:
                command = application_command(sober, custom)
                session.launch(command, width, height)
                error = ""
            except Exception as exc:
                error = str(exc)
            self.bridge.session_ready.emit(generation, error)

        threading.Thread(target=launch, daemon=True).start()

    def session_started(self, generation, error):
        if generation != self.session_generation:
            return
        self.session_launching = False
        self.launch_session_btn.setEnabled(not self.busy)
        if error:
            self.set_session_status(error)
            self.show_error(error)
        else:
            self.set_session_status(
                "Waiting for the game's window. Keep the game open, then select it here."
            )
            self.session_tick()

    def populate_targets(self, windows):
        previous = self.target.currentData()
        self.available_targets = list(windows)
        self.target.blockSignals(True)
        self.target.clear()
        self.target.addItem(
            "Any active window" if self.mode.currentIndex() == 0 else "Choose an open window…", None
        )
        for window in windows:
            self.target.addItem(f"{window.title} · PID {window.pid}", window)
        at = self.target_index(previous)
        if (
            previous is not None
            and at < 0
            and self.mode.currentIndex() == 0
            and getattr(self, "last_target_mode", 0) == 0
        ):
            self.target.addItem("Unavailable · " + previous.title, previous)
            at = self.target.count() - 1
        self.last_target_mode = self.mode.currentIndex()
        self.target.setCurrentIndex(
            at
            if previous is not None and at >= 0
            else 1
            if self.mode.currentIndex() == 2 and len(windows) == 1
            else 0
        )
        self.target.blockSignals(False)
        self.update_run_summary()
        if self.window_picker is not None and self.mode.currentIndex() == 2:
            self.window_picker.set_windows(windows)

    def target_index(self, target):
        if target is None:
            return 0
        for index in range(self.target.count()):
            value = self.target.itemData(index)
            if value is not None and (value.id, value.pid, value.wm_class) == (
                target.id,
                target.pid,
                target.wm_class,
            ):
                return index
        return -1

    def session_tick(self):
        session = self.game_session
        running = session.process is not None and session.process.poll() is None
        self.close_session_btn.setEnabled(running and not self.busy)
        if not running:
            if session.process is not None:
                self.set_session_status(
                    "Game session closed. Open diagnostics if it exited unexpectedly."
                )
                if self.session_targets:
                    self.session_targets = []
                    if self.mode.currentIndex() == 2:
                        self.populate_targets([])
            return
        if self.session_query_pending:
            return
        self.session_query_pending = True
        generation = self.session_generation

        def query():
            try:
                windows = session.windows()
                error = ""
            except Exception as exc:
                windows = []
                error = str(exc)
            self.bridge.session_windows.emit(generation, windows, error)

        threading.Thread(target=query, daemon=True).start()

    def session_windows_ready(self, generation, windows, error):
        if generation != self.session_generation:
            return
        self.session_query_pending = False
        if error:
            if time.monotonic() - self.game_session.started_at > 20:
                self.set_session_status(
                    "Session input is unavailable. Open diagnostics; no desktop input will be used."
                )
            return
        changed = windows != self.session_targets
        self.session_targets = windows
        self.set_session_status(
            "Separate game display connected. Only its virtual mouse/keyboard receive playback."
            if windows
            else "Display connected. Waiting for the game window; an existing app instance may need closing first."
        )
        if changed and self.mode.currentIndex() == 2 and not self.busy:
            self.populate_targets(windows)

    def close_game_session(self):
        if self.busy:
            return
        if (
            QMessageBox.question(
                self,
                "Close game session?",
                "This closes the game launched by Studio. Unsaved game progress may be lost.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        self.game_session.close()
        self.session_generation += 1
        self.session_query_pending = False
        self.session_targets = []
        if self.mode.currentIndex() == 2:
            self.populate_targets([])

    def show_session_diagnostics(self):
        text = "\n".join(list(self.game_session.log))[-20000:]
        QMessageBox.information(
            self,
            "Game session diagnostics",
            text
            or "Launch a game session to collect diagnostics. Gamescope and the selected game must be installed.",
        )
