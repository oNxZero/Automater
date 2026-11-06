"""Qt signals for the portal session shared by the editor and CLI."""

from PySide6.QtCore import QObject, Signal

from .portal_session import SERVICE as SERVICE
from .portal_session import PortalPointer as PortalPointer
from .portal_session import PortalSession


class PortalConnection(QObject):
    ready = Signal()
    failed = Signal(str)
    revoked = Signal()

    def __init__(self, parent=None, bus_address=None, token_path=None):
        super().__init__(parent)
        self._connection = PortalSession(
            bus_address=bus_address,
            token_path=token_path,
            on_ready=self.ready.emit,
            on_failed=self.failed.emit,
            on_revoked=self.revoked.emit,
        )

    def __getattr__(self, name):
        connection = self.__dict__.get("_connection")
        if connection is None:
            raise AttributeError(name)
        return getattr(connection, name)

    def connect_pointer(self):
        self._connection.connect_pointer()

    def close(self):
        self._connection.close()

    def locate(self, point):
        return self._connection.locate(point)

    def move(self, point):
        self._connection.move(point)

    @property
    def thread(self):
        return self._connection.thread

    @property
    def active(self):
        return self._connection.active

    @active.setter
    def active(self, value):
        self._connection.active = value

    @property
    def streams(self):
        return self._connection.streams

    @streams.setter
    def streams(self, value):
        self._connection.streams = value
