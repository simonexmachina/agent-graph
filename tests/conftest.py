"""Shared pytest fixtures."""

from __future__ import annotations

import os

import pytest

# Used by integration tests that create a PostgresBackend directly.
TEST_DATABASE_URL = os.environ.get(
    "AGENTGRAPH_TEST_DATABASE_URL",
    "postgresql://agentgraph:agentgraph@localhost:5432/agentgraph_test",
)


@pytest.fixture(autouse=True)
def _use_sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use an in-memory SQLite backend for all unit tests.

    Integration tests that need PostgreSQL create a PostgresBackend directly
    inside their own fixtures and call set_backend() themselves.
    """
    monkeypatch.setenv("AGENTGRAPH_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTGRAPH_BACKEND_SQLITE_PATH", ":memory:")
    # Keep postgres URL available so pg_backend fixtures can still read it.
    monkeypatch.setenv("AGENTGRAPH_DATABASE_URL", TEST_DATABASE_URL)

    import agentgraph.config as cfg
    import agentgraph.core.context as ctx

    monkeypatch.setattr(cfg, "_settings", None)
    monkeypatch.setattr(ctx, "_backend", None)
