"""Shared pytest fixtures."""

# pyright: reportUnusedFunction=false

import pytest


@pytest.fixture(autouse=True)
def _use_sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use an in-memory SQLite backend for all unit tests."""
    monkeypatch.setenv("AGENTGRAPH_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTGRAPH_BACKEND_SQLITE_PATH", ":memory:")

    import agentgraph.config as cfg
    import agentgraph.core.context as ctx

    monkeypatch.setattr(cfg, "_settings", None)
    monkeypatch.setattr(ctx, "_backend", None)
