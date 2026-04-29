"""Tests for the observation API endpoint and dwell evaluator."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agentgraph.server.models import BlurEvent, FocusEvent


@pytest.fixture
def client() -> TestClient:
    """Create a test client with all backend I/O mocked out."""
    mock_backend = MagicMock()
    mock_backend.initialize = AsyncMock()
    mock_backend.close = AsyncMock()
    mock_backend.insert_observation = AsyncMock()
    mock_backend.patch_observation_meta = AsyncMock()

    with (
        patch("agentgraph.backends.get_backend_class", return_value=lambda *a: mock_backend),
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.server.app.run_dwell_loop", new_callable=AsyncMock),
        patch("agentgraph.server.app.setup_sync"),
        patch("agentgraph.server.app.AsyncIOScheduler"),
    ):
        from agentgraph.server.app import app
        return TestClient(app, raise_server_exceptions=True)


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_focus_event_model() -> None:
    e = FocusEvent(
        type="focus",
        url="https://docs.google.com/document/d/abc/edit",
        title="My Doc",
        tab_id=1,
        timestamp=datetime.now(timezone.utc),
    )
    assert e.type == "focus"
    assert e.tab_id == 1


def test_blur_event_model() -> None:
    e = BlurEvent(
        type="blur",
        url="https://docs.google.com/document/d/abc/edit",
        tab_id=1,
        timestamp=datetime.now(timezone.utc),
    )
    assert e.type == "blur"


@pytest.mark.integration
async def test_observe_focus_persists() -> None:
    from agentgraph.backends.postgres.backend import PostgresBackend
    from agentgraph.config import get_settings
    from agentgraph.core.context import set_backend

    settings = get_settings()
    backend = PostgresBackend(settings.database_url)
    await backend.initialize()
    set_backend(backend)

    ts = datetime.now(timezone.utc)
    await backend.insert_observation(
        event_type="focus",
        url="https://docs.google.com/document/d/abc/edit",
        title="My Doc",
        tab_id=42,
        timestamp=ts,
        meta=None,
    )

    pool = backend._pool_or_raise()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM observations WHERE tab_id = 42 AND event_type = 'focus'"
        )

    assert row is not None
    assert row["url"] == "https://docs.google.com/document/d/abc/edit"
    assert row["evaluated"] is False

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM observations WHERE tab_id = 42")
    await backend.close()
