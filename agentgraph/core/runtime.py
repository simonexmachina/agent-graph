"""Runtime helpers for constructing configured backends."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from agentgraph.core.storage import StorageBackend


def create_backend() -> StorageBackend:
    """Create the configured storage backend without initialising it."""
    from agentgraph.backends import get_backend_class
    from agentgraph.config import get_settings

    settings = get_settings()
    backend_class: Any = get_backend_class(settings.backend)
    if settings.backend == "sqlite":
        return backend_class(settings.backend_sqlite_path, settings.backend_sqlite_vector_mode)
    return backend_class(settings)


@asynccontextmanager
async def backend_context() -> AsyncGenerator[StorageBackend, None]:
    """Initialise the configured backend, set graph context, and close it."""
    from agentgraph.core.context import clear_backend, set_backend

    backend = create_backend()
    await backend.initialize()
    set_backend(backend)
    try:
        yield backend
    finally:
        await backend.close()
        clear_backend()
