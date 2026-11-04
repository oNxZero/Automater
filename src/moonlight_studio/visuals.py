"""Explicit on-screen guides and pointer connection UI."""

from PySide6.QtCore import QTimer

from .overlay import OverlayGroup, pointer_path


class VisualsMixin:
    def connect_pointer(self):
        if self.busy:
            return
        from .portal import PortalConnection

        if self.portal_connection:
            self.portal_connection.close()
        self.portal_connection = PortalConnection(self)
        connection = self.portal_connection
        connection.ready.connect(
            lambda: self.pointer_ready() if self.portal_connection is connection else None
        )
        connection.failed.connect(
            lambda error: (
                self.pointer_failed(error) if self.portal_connection is connection else None
            )
        )
        connection.revoked.connect(
            lambda: self.pointer_revoked() if self.portal_connection is connection else None
        )
        self.connecting_pointer = True
        self.update_busy(True)
        self.status.setText(
            "Approve pointer control and select your monitors in the desktop dialog · F12 cancels"
        )
        self.portal_connection.connect_pointer()

    def pointer_ready(self):
        if not self.connecting_pointer:
            return
        self.connecting_pointer = False
        self.update_busy(False)
        self.status.setText("Wayland pointer control connected · starting coordinates are ready")

    def pointer_failed(self, error):
        if not self.connecting_pointer:
            return
        self.connecting_pointer = False
        self.update_busy(False)
        self.show_error(error)

    def pointer_revoked(self):
        if self.busy:
            self.stop()
        self.update_run_summary()
        self.show_error("Desktop pointer permission ended. Reconnect in Settings → Start.")

    def close_overlay(self):
        self.overlay_generation = getattr(self, "overlay_generation", 0) + 1
        if getattr(self, "overlay", None) is not None:
            self.overlay.close()
            self.overlay = None
        self.screen_picking = False

    def pick_screen_point(self, callback=None):
        if self.busy or self.mode.currentIndex():
            return
        self.close_overlay()
        self.screen_picking = True
        self.update_busy(True)

        def chosen(point):
            self.close_overlay()
            self.update_busy(False)
            import os

            from PySide6.QtWidgets import QApplication

            if (
                QApplication.platformName() == "xcb"
                and os.environ.get("XDG_SESSION_TYPE") != "wayland"
                and not os.environ.get("WAYLAND_DISPLAY")
            ):
                from .pointer import X11Pointer

                provider = None
                try:
                    provider = X11Pointer()
                    point = provider.position()
                except Exception as exc:
                    self.show_error(f"Could not read the chosen X11 point: {exc}")
                    return
                finally:
                    if provider is not None:
                        provider.close()
            if callable(callback):
                generation = self.overlay_generation
                QTimer.singleShot(
                    60,
                    self,
                    lambda: (
                        callback(point)
                        if generation == self.overlay_generation and not self.busy
                        else None
                    ),
                )
            else:
                self.start_x.setValue(point[0])
                self.start_y.setValue(point[1])
                self.start_enabled.setChecked(True)
                self.status.setText(f"Starting point selected: {point[0]}, {point[1]}")

        def cancelled():
            self.close_overlay()
            self.update_busy(False)
            self.status.setText("Point selection cancelled")

        self.overlay = OverlayGroup(chosen=chosen, cancelled=cancelled)
        self.overlay.show()

    def show_pointer_guide(self, points):
        self.close_overlay()
        self.overlay = OverlayGroup(points=points)
        self.overlay.show()

    def preview_start_point(self):
        if self.busy:
            return
        if self.mode.currentIndex():
            self.show_error(
                "Background coordinates belong to the target window; use Test mode to preview its sequence"
            )
            return
        self.show_pointer_guide(pointer_path([], (self.start_x.value(), self.start_y.value())))

    def preview_pointer(self):
        if self.busy:
            return
        rows = self.selected_rows()
        steps = [self.model.steps[r] for r in rows]
        if not any(s.action == "move" for s in steps):
            self.show_error("Select a pointer movement action to preview its path")
            return
        if self.mode.currentIndex():
            self.show_error(
                "Screen guides use desktop coordinates. Background movement is relative to its target window."
            )
            return

        def show(origin):
            self.show_pointer_guide(pointer_path(steps, origin))
            self.status.setText(
                "Pointer path guide · approximate: desktop acceleration can change relative movement"
            )

        if self.start_enabled.isChecked():
            origin = pointer_path(
                self.model.steps[: rows[0]], (self.start_x.value(), self.start_y.value())
            )[-1]
            show((origin.x(), origin.y()))
        else:
            self.pick_screen_point(show)
