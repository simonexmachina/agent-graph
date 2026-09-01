"""Shared pytest fixtures."""

# pyright: reportUnusedFunction=false

import pytest


@pytest.fixture(autouse=True)
def _use_sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use an in-memory SQLite backend for all unit tests."""
    monkeypatch.setenv("AGENTGRAPH_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTGRAPH_BACKEND_SQLITE_PATH", ":memory:")

    # Pin the transport: `auto` would otherwise reach a server that happens to be
    # running on this machine, so the same test would pass or fail depending on
    # whether the developer had `agentgraph serve` up — and it would query the real
    # database instead of the in-memory one above. Tests that exercise the server
    # transport set this themselves or build a client directly.
    monkeypatch.setenv("AGENTGRAPH_QUERY_TRANSPORT", "in-process")
    monkeypatch.setenv("AGENTGRAPH_SERVER_UDS_PATH", "none")

    import agentgraph.config as cfg
    import agentgraph.core.context as ctx

    monkeypatch.setattr(cfg, "_settings", None)
    monkeypatch.setattr(ctx, "_backend", None)
