"""Tests for the observation API endpoint and dwell evaluator."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from agentgraph.server.models import BlurEvent, FocusEvent


@pytest.fixture
def client() -> TestClient:
    # Import after patching to avoid real DB/dwell startup
    with patch("agentgraph.server.app.apply_schema", new_callable=AsyncMock), \
         patch("agentgraph.server.app.close_pool", new_callable=AsyncMock), \
         patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.server.app.run_dwell_loop", new_callable=AsyncMock):
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
    from agentgraph.db.connection import apply_schema, get_pool, close_pool

    await apply_schema()
    pool = await get_pool()

    ts = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO observations (event_type, url, title, tab_id, timestamp) VALUES ($1,$2,$3,$4,$5)",
            "focus",
            "https://docs.google.com/document/d/abc/edit",
            "My Doc",
            42,
            ts,
        )
        row = await conn.fetchrow(
            "SELECT * FROM observations WHERE tab_id = 42 AND event_type = 'focus'"
        )

    assert row is not None
    assert row["url"] == "https://docs.google.com/document/d/abc/edit"
    assert row["evaluated"] is False

    await close_pool()
