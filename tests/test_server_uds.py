"""Tests for the server's Unix socket listener."""

from __future__ import annotations

import socket
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from agentgraph.server import uds


@pytest.fixture
def sock_dir() -> Iterator[Path]:
    """A directory short enough for AF_UNIX; pytest's tmp_path exceeds sun_path."""
    with tempfile.TemporaryDirectory(prefix="ag-") as name:
        yield Path(name)


def test_bind_socket_creates_owner_only_socket(sock_dir: Path) -> None:
    path = sock_dir / "nested" / "ag.sock"

    sock = uds.bind_socket(path)
    try:
        assert path.exists()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert uds.socket_is_live(path)
    finally:
        sock.close()
        uds.unlink_socket(path)


def test_socket_is_live_is_false_for_missing_and_stale_sockets(sock_dir: Path) -> None:
    missing = sock_dir / "missing.sock"
    assert uds.socket_is_live(missing) is False

    # A socket file with nothing listening — what a killed server leaves behind.
    stale = sock_dir / "stale.sock"
    bound = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    bound.bind(str(stale))
    bound.close()
    assert stale.exists()
    assert uds.socket_is_live(stale) is False


def test_bind_socket_replaces_a_stale_socket(sock_dir: Path) -> None:
    path = sock_dir / "ag.sock"
    abandoned = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    abandoned.bind(str(path))
    abandoned.close()

    sock = uds.bind_socket(path)
    try:
        assert uds.socket_is_live(path)
    finally:
        sock.close()
        uds.unlink_socket(path)


def test_bind_socket_refuses_to_steal_a_live_socket(sock_dir: Path) -> None:
    path = sock_dir / "ag.sock"
    first = uds.bind_socket(path)
    try:
        with pytest.raises(OSError, match="already listening"):
            uds.bind_socket(path)
        # The running server's socket must survive the failed attempt.
        assert uds.socket_is_live(path)
    finally:
        first.close()
        uds.unlink_socket(path)


def test_unlink_socket_is_idempotent(sock_dir: Path) -> None:
    path = sock_dir / "gone.sock"
    uds.unlink_socket(path)
    uds.unlink_socket(path)


def test_bind_socket_explains_an_over_long_path(sock_dir: Path) -> None:
    """A deep AGENTGRAPH_CONFIG_DIR must not surface as 'AF_UNIX path too long'."""
    path = sock_dir / ("d" * 60) / ("n" * 60) / "ag.sock"

    with pytest.raises(uds.SocketPathTooLongError, match="AF_UNIX limit"):
        uds.bind_socket(path)
    # The failed bind must not leave the directory tree behind.
    assert not path.parent.exists()


def test_socket_is_live_is_false_for_an_over_long_path(sock_dir: Path) -> None:
    assert uds.socket_is_live(sock_dir / ("x" * 200) / "ag.sock") is False


def test_release_owned_socket_removes_only_a_claimed_socket(sock_dir: Path) -> None:
    """Uvicorn's SIGTERM path skips serve()'s finally, so the app hook does this."""
    path = sock_dir / "ag.sock"
    sock = uds.bind_socket(path)
    sock.close()
    assert path.exists()

    # Not claimed: a TCP-only server must not delete another server's socket.
    uds.set_owned_socket(None)
    uds.release_owned_socket()
    assert path.exists()

    uds.set_owned_socket(path)
    uds.release_owned_socket()
    assert not path.exists()


def test_release_owned_socket_is_idempotent(sock_dir: Path) -> None:
    path = sock_dir / "ag.sock"
    uds.set_owned_socket(path)
    uds.release_owned_socket()
    uds.release_owned_socket()
    assert not path.exists()
