"""Shared pytest fixtures."""

from __future__ import annotations

import os

import pytest

# Point integration tests at a separate database so they never touch
# the production agentgraph database.
TEST_DATABASE_URL = os.environ.get(
    "AGENTGRAPH_TEST_DATABASE_URL",
    "postgresql://agentgraph:agentgraph@localhost:5432/agentgraph_test",
)


@pytest.fixture(autouse=True)
def _use_test_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect all DB connections to the test database for every test."""
    monkeypatch.setenv("AGENTGRAPH_DATABASE_URL", TEST_DATABASE_URL)

    # Reset the settings and pool singletons so they pick up the new URL.
    import agentgraph.config as cfg
    import agentgraph.db.connection as conn

    monkeypatch.setattr(cfg, "_settings", None)
    monkeypatch.setattr(conn, "_pool", None)
