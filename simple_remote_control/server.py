from collections.abc import Callable
import ctypes
import hashlib
import os
import socket
import struct
import sys

from qgis.PyQt.QtCore import (
    QDir,
    QLockFile,
    QObject,
    QStandardPaths,
    QVersionNumber,
    pyqtSignal,
    qVersion,
)
from qgis.PyQt.QtNetwork import QLocalServer, QLocalSocket

from .protocol import handle_request

PIPE_PREFIX = "\\\\.\\pipe\\"
DEFAULT_NAME = "qgis-remote-control"
DEFAULT_ABSOLUTE = (
    PIPE_PREFIX + DEFAULT_NAME
    if sys.platform == "win32"
    else "/tmp/" + DEFAULT_NAME + ".sock"
)
MAX_FRAME_BYTES = 1024 * 1024
MAX_QUEUED_REPLY_BYTES = 2 * MAX_FRAME_BYTES


def _is_simple_name(name: str) -> bool:
    return (
        bool(name.strip())
        and name not in (".", "..")
        and not ("/" in name or "\\" in name or any(ord(char) < 32 for char in name))
    )


def _listen_name(mode: str, value: str) -> str:
    if mode == "qt":
        if not _is_simple_name(value):
            raise ValueError("Enter a socket name without path separators.")
        return value

    if sys.platform == "win32":
        name = value[len(PIPE_PREFIX) :]
        if not value.lower().startswith(PIPE_PREFIX) or not _is_simple_name(name):
            raise ValueError(f"Enter a local pipe path such as {DEFAULT_ABSOLUTE}.")
        return PIPE_PREFIX + name
    if not value.startswith("/") or value.endswith("/") or "\0" in value:
        raise ValueError("Enter an absolute Unix socket path.")
    return value


def _lock_pipe(name: str) -> QLockFile:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.GenericDataLocation
    )
    if not base:
        raise OSError("Could not find a directory for the named pipe lock.")
    directory = os.path.join(base, "simple_remote_control")
    os.makedirs(directory, exist_ok=True)
    full_name = name if name.startswith(PIPE_PREFIX) else PIPE_PREFIX + name
    digest = hashlib.sha256(full_name.casefold().encode("utf-8")).hexdigest()
    lock = QLockFile(os.path.join(directory, f"{digest}.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        if lock.error() == QLockFile.LockError.LockFailedError:
            raise OSError("Another plugin instance is using this named pipe.")
        raise OSError("Could not lock the named pipe for this plugin instance.")
    return lock


def _is_current_user(descriptor: int) -> bool:
    if sys.platform == "win32":
        # The pipe ACL checks the user and Qt 6.11 rejects remote clients.
        return True
    if sys.platform == "darwin":
        getpeereid = ctypes.CDLL(None).getpeereid
        getpeereid.argtypes = (
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
        )
        uid, gid = ctypes.c_uint(), ctypes.c_uint()
        result = getpeereid(descriptor, ctypes.byref(uid), ctypes.byref(gid))
        return result == 0 and uid.value == os.geteuid()

    credentials = struct.Struct("iII")
    with socket.fromfd(descriptor, socket.AF_UNIX, socket.SOCK_STREAM) as peer:
        _, uid, _ = credentials.unpack(
            peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, credentials.size)
        )
    return uid == os.geteuid()


class LocalServer(QObject):
    running_changed = pyqtSignal(bool)

    def __init__(self, dispatch: Callable[[str, dict], None]):
        super().__init__()
        self._dispatch = dispatch
        self._listener = QLocalServer(self)
        self._listener.newConnection.connect(self._accept_connections)
        self._clients: set[QLocalSocket] = set()
        self._pipe_lock: QLockFile | None = None

    @property
    def running(self) -> bool:
        return self._listener.isListening()

    def start(self, mode: str, value: str) -> None:
        if self.running:
            return
        if sys.platform not in ("darwin", "linux", "win32"):
            raise OSError("This operating system is unsupported.")

        name = _listen_name(mode, value)
        if sys.platform == "win32":
            version, _ = QVersionNumber.fromString(qVersion())
            if QVersionNumber.compare(version, QVersionNumber(6, 11)) < 0:
                raise OSError(
                    "Local-only Windows named pipes require Qt 6.11 or later."
                )
            self._listener.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
            self._pipe_lock = _lock_pipe(name)
        else:
            path = os.path.join(QDir.tempPath(), name) if mode == "qt" else name
            if os.path.lexists(path):
                raise OSError(f"The socket path {path!r} is already occupied.")

        if not self._listener.listen(name):
            self._unlock_pipe()
            raise OSError(self._listener.errorString())
        self.running_changed.emit(True)

    def stop(self) -> None:
        was_running = self.running
        self._listener.close()
        for client in tuple(self._clients):
            self._disconnect(client)
        self._unlock_pipe()
        if was_running:
            self.running_changed.emit(False)

    def _unlock_pipe(self) -> None:
        if self._pipe_lock is not None:
            self._pipe_lock.unlock()
            self._pipe_lock = None

    def _accept_connections(self) -> None:
        while self._listener.hasPendingConnections():
            client = self._listener.nextPendingConnection()
            try:
                allowed = _is_current_user(int(client.socketDescriptor()))
            except OSError:
                allowed = False
            if not allowed:
                client.abort()
                client.deleteLater()
                continue

            self._clients.add(client)
            client.setReadBufferSize(MAX_FRAME_BYTES + 1)
            client.disconnected.connect(lambda client=client: self._forget(client))
            client.readyRead.connect(lambda client=client: self._read_requests(client))
            self._read_requests(client)

    def _read_requests(self, client: QLocalSocket) -> None:
        while client in self._clients and client.canReadLine():
            frame = bytes(client.readLine())[:-1]
            if len(frame) > MAX_FRAME_BYTES:
                self._disconnect(client)
                return

            reply = handle_request(frame, self._dispatch)
            if reply is not None and client in self._clients:
                if client.bytesToWrite() + len(reply) > MAX_QUEUED_REPLY_BYTES:
                    self._disconnect(client)
                    return
                client.write(reply)

        if client in self._clients and client.bytesAvailable() > MAX_FRAME_BYTES:
            self._disconnect(client)

    def _disconnect(self, client: QLocalSocket) -> None:
        client.abort()
        self._forget(client)

    def _forget(self, client: QLocalSocket) -> None:
        if client in self._clients:
            self._clients.remove(client)
            client.deleteLater()
