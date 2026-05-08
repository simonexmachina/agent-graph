"""Tests for the /fetch-url endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    mock_backend = MagicMock()
    mock_backend.initialize = AsyncMock()
    mock_backend.close = AsyncMock()

    with (
        patch("agentgraph.backends.get_backend_class", return_value=lambda *_: mock_backend),
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.server.app.setup_sync"),
        patch("agentgraph.server.app.AsyncIOScheduler"),
    ):
        from agentgraph.server.app import app
        return TestClient(app, raise_server_exceptions=True)


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_fetch_url_unrecognised(client: TestClient) -> None:
    resp = client.post("/fetch-url", json={"url": "https://example.com/unknown"})
    assert resp.status_code == 202
    assert resp.json()["status"] == "ignored"
