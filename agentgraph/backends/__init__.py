"""Backend registry: maps backend names to StorageBackend implementations.

The built-in SQLite backend is always available. Additional backends can be
registered by third-party packages via the ``agentgraph.backends`` entry point
group.
"""

from __future__ import annotations

import importlib.metadata
import logging

from agentgraph.core.storage import StorageBackend

logger = logging.getLogger(__name__)

_registry: dict[str, type[StorageBackend]] = {}
_builtin_import_errors: dict[str, ImportError] = {}


def _ensure_loaded() -> None:
    if _registry:
        return
    _load_builtins()
    _load_plugins()


def _load_builtins() -> None:
    try:
        from agentgraph.backends.sqlite.backend import SQLiteBackend

        _registry["sqlite"] = SQLiteBackend
    except ImportError as exc:
        _builtin_import_errors["sqlite"] = exc
        logger.debug("SQLite backend unavailable (aiosqlite not installed)", exc_info=True)


def _load_plugins() -> None:
    for ep in importlib.metadata.entry_points(group="agentgraph.backends"):
        try:
            _registry[ep.name] = ep.load()
        except Exception as exc:
            logger.warning("Failed to load backend %r: %s", ep.name, exc)


def get_backend_class(name: str) -> type[StorageBackend]:
    _ensure_loaded()
    if name not in _registry:
        if name in _builtin_import_errors:
            raise ValueError(
                "SQLite backend is unavailable. Run this project with `uv run` or install "
                "the project dependencies."
            ) from _builtin_import_errors[name]
        raise ValueError(
            f"Unknown backend {name!r}. Available: {sorted(_registry)}"
        )
    return _registry[name]
