"""Module-level StorageBackend singleton."""

from __future__ import annotations

from agentgraph.core.storage import StorageBackend

_backend: StorageBackend | None = None


def set_backend(backend: StorageBackend) -> None:
    global _backend
    _backend = backend


def clear_backend() -> None:
    global _backend
    _backend = None


def get_backend() -> StorageBackend:
    if _backend is None:
        raise RuntimeError(
            "No storage backend initialized. "
            "Call set_backend() before using the graph layer."
        )
    return _backend
