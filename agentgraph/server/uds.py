"""Unix socket listener for the local server.

Several coding-agent sandboxes deny loopback TCP outright while still allowing an
allowlisted Unix socket, so the server listens on both and clients prefer the socket.
"""

from __future__ import annotations

import logging
import os
import socket
from pathlib import Path

logger = logging.getLogger(__name__)

# Owner-only. Uvicorn's own bind_socket() would chmod the socket to 0o666, which
# would let any local account query the graph.
SOCKET_MODE = 0o600

# sun_path is 104 bytes on macOS/BSD and 108 on Linux. Take the smaller limit so a
# path that works on one platform is not silently rejected on the other.
MAX_SOCKET_PATH_BYTES = 103


class SocketPathTooLongError(OSError):
    """The configured socket path exceeds the platform's AF_UNIX limit."""


def check_path_length(path: Path) -> None:
    """Raise a self-explanatory error instead of a bare 'AF_UNIX path too long'."""
    encoded = len(str(path).encode())
    if encoded > MAX_SOCKET_PATH_BYTES:
        raise SocketPathTooLongError(
            f"Socket path is {encoded} bytes, over the {MAX_SOCKET_PATH_BYTES}-byte "
            f"AF_UNIX limit: {path}. Set AGENTGRAPH_SERVER_UDS_PATH to a shorter path, "
            "or to 'none' to serve over TCP only."
        )


def socket_is_live(path: Path) -> bool:
    """Return whether a server is currently accepting connections on the socket."""
    if not path.exists() or len(str(path).encode()) > MAX_SOCKET_PATH_BYTES:
        return False
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.2)
        probe.connect(str(path))
    except (ConnectionRefusedError, FileNotFoundError, TimeoutError, PermissionError, OSError):
        return False
    else:
        return True
    finally:
        probe.close()


def bind_socket(path: Path, backlog: int = 2048) -> socket.socket:
    """Bind and listen on the Unix socket, clearing a socket left by a dead server.

    Raises OSError when another server is already listening, rather than silently
    unlinking its socket and stealing the address.
    """
    check_path_length(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if socket_is_live(path):
            raise OSError(f"Another AgentGraph server is already listening on {path}")
        logger.info("Removing socket left by a previous server: %s", path)
        path.unlink()

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(str(path))
        os.chmod(path, SOCKET_MODE)
        sock.listen(backlog)
    except BaseException:
        sock.close()
        path.unlink(missing_ok=True)
        raise
    return sock


def unlink_socket(path: Path) -> None:
    """Remove the socket file on shutdown; we bound it, so uvicorn will not."""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not remove socket %s: %s", path, exc)


_owned_socket: Path | None = None


def set_owned_socket(path: Path | None) -> None:
    """Record that this process bound ``path`` and is responsible for removing it."""
    global _owned_socket
    _owned_socket = path


def release_owned_socket() -> None:
    """Remove the socket this process bound, if any.

    Called from the app's shutdown hook rather than a ``finally`` around
    ``uvicorn.Server.run``: uvicorn's signal handling ends the process without
    unwinding that frame, so a ``finally`` there never runs on SIGTERM. The lifespan
    shutdown does run, and only the process that bound the socket sets this, so a
    TCP-only server cannot delete another server's socket.
    """
    global _owned_socket
    if _owned_socket is None:
        return
    unlink_socket(_owned_socket)
    _owned_socket = None
