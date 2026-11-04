"""Temporary pointer guides. Preview windows never emit input or capture the mouse."""

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget


def pointer_path(steps, origin, limit=1500):
    """Bound visual samples while preserving the exact cumulative endpoint."""
    points = [QPointF(*origin)]
    stride = max(1, (len(steps) + limit - 1) // limit)
    position = QPointF(*origin)
    for index, step in enumerate(steps):
        if step.enabled and step.action == "move":
            position += QPointF(step.x, step.y)
            if index % stride == 0:
                points.append(QPointF(position))
    if position != points[-1]:
        points.append(position)
    return points


class PointerOverlay(QWidget):
    chosen = Signal(object)
    cancelled = Signal()

    def __init__(self, screen, points=(), picking=False):
        flags = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        if not picking:
            flags |= Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
        super().__init__(None, flags)
        self.screen_geometry = screen.geometry()
        self.points, self.picking = list(points), picking
        self.local_cursor = None
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating, not picking)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not picking)
        self.setMouseTracking(picking)
        self.setFocusPolicy(Qt.StrongFocus if picking else Qt.NoFocus)
        self.setScreen(screen)
        self.setGeometry(self.screen_geometry)
        self.opacity = 0.0
        self.fade = QVariantAnimation(self)
        self.fade.setDuration(160)
        self.fade.setStartValue(0.0)
        self.fade.setEndValue(1.0)
        self.fade.setEasingCurve(QEasingCurve.OutCubic)
        self.fade.valueChanged.connect(self.animate)

    def animate(self, value):
        self.opacity = value
        self.update()

    def reveal(self):
        self.showFullScreen()
        if self.picking:
            self.activateWindow()
            self.setFocus()
        self.fade.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setOpacity(self.opacity)
        if self.picking:
            painter.fillRect(self.rect(), QColor(12, 14, 24, 60))
        origin = self.screen_geometry.topLeft()
        painter.setPen(QPen(QColor("#b5a4fa"), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if self.points:
            path = QPainterPath(self.points[0] - origin)
            for point in self.points[1:]:
                path.lineTo(point - origin)
            painter.drawPath(path)
            markers = (
                (self.points[0], self.points[-1]) if len(self.points) > 1 else (self.points[0],)
            )
            for index, point in enumerate(markers):
                p = point - origin
                painter.setBrush(QColor("#75d6c0" if index == 0 else "#b5a4fa"))
                painter.drawEllipse(p, 8, 8)
                painter.drawText(
                    QRectF(p.x() + 14, p.y() - 12, 220, 30),
                    Qt.AlignVCenter,
                    f"{'Start' if index == 0 else 'End'} {point.x():.0f}, {point.y():.0f}",
                )
        text = (
            "Click a starting point · Right-click / Esc / F12 cancels"
            if self.picking
            else "Pointer path preview · approximate relative motion · closes in 4 s"
        )
        if self.local_cursor is not None:
            point = self.local_cursor
            painter.drawLine(QPointF(point.x() - 16, point.y()), QPointF(point.x() + 16, point.y()))
            painter.drawLine(QPointF(point.x(), point.y() - 16), QPointF(point.x(), point.y() + 16))
            global_point = point + origin
            text = f"{global_point.x():.0f}, {global_point.y():.0f} · Click to choose · Esc cancels"
        box = QRectF(24, 24, min(680, self.width() - 48), 46)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#202336"))
        painter.drawRoundedRect(box, 12, 12)
        painter.setPen(QColor("#e2e5f4"))
        painter.drawText(box.adjusted(16, 0, -16, 0), Qt.AlignVCenter, text)

    def mouseMoveEvent(self, event):
        self.local_cursor = event.position()
        self.update()

    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        if not self.picking:
            return
        if event.button() == Qt.LeftButton:
            point = event.position() + self.screen_geometry.topLeft()
            self.chosen.emit((round(point.x()), round(point.y())))
        elif event.button() == Qt.RightButton:
            self.cancelled.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_F12):
            self.cancelled.emit()
        else:
            super().keyPressEvent(event)


class OverlayGroup:
    def __init__(self, points=(), chosen=None, cancelled=lambda: None):
        self.windows = []
        self.done = False
        self._chosen, self._cancelled = chosen, cancelled
        for screen in QApplication.screens():
            window = PointerOverlay(screen, points, picking=chosen is not None)
            window.chosen.connect(self.choose)
            window.cancelled.connect(self.cancel)
            self.windows.append(window)

    def show(self):
        for window in self.windows:
            window.reveal()
        if self._chosen is None:
            self.timer = QTimer(self.windows[0])
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(self.close)
            self.timer.start(4000)

    def choose(self, point):
        if self.done:
            return
        self.close()
        self._chosen(point)

    def cancel(self):
        if self.done:
            return
        self.close()
        self._cancelled()

    def close(self):
        if self.done:
            return
        self.done = True
        for window in self.windows:
            window.close()
            window.deleteLater()
