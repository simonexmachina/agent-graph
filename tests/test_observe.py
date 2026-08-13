"""Tests for the /report-dwell endpoint."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agentgraph.connectors.base import EntityBatch, EntityRecord, SourceReference
from agentgraph.core.context import set_backend
from agentgraph.server.app import viewer_url


@pytest.fixture
def client() -> TestClient:
    mock_backend = MagicMock()
    mock_backend.initialize = AsyncMock()
    mock_backend.close = AsyncMock()

    def backend_factory(*_: object) -> MagicMock:
        return mock_backend

    with (
        patch("agentgraph.backends.get_backend_class", return_value=backend_factory),
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


def test_viewer_url_uses_localhost_for_wildcard_hosts() -> None:
    assert viewer_url("0.0.0.0", 8765) == "http://127.0.0.1:8765/viewer"
    assert viewer_url("::", 8765) == "http://127.0.0.1:8765/viewer"


def test_viewer_url_brackets_ipv6_hosts() -> None:
    assert viewer_url("::1", 8765) == "http://[::1]:8765/viewer"


def test_report_dwell_unrecognised(client: TestClient) -> None:
    resp = client.post("/report-dwell", json={"url": "https://example.com/unknown", "dwell_ms": 15000})
    assert resp.status_code == 202
    assert resp.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_cli_meta_includes_dynamic_connector_patterns() -> None:
    from agentgraph.server.cli_api import cli_meta

    connector = MagicMock()
    connector.source = "rss"
    connector.observation_url_patterns = AsyncMock(
        return_value=["https://example.com/articles/*", "https://example.com/articles/*"]
    )
    settings = MagicMock(dwell_threshold_seconds=3)

    with (
        patch("agentgraph.connectors.registry.get_all_connectors", return_value=[connector]),
        patch("agentgraph.config.get_settings", return_value=settings),
    ):
        result = await cli_meta()

    assert result["url_patterns"] == ["https://example.com/articles/*"]
    connector.observation_url_patterns.assert_awaited_once()


@pytest.mark.asyncio
async def test_cli_meta_can_skip_dynamic_connector_patterns() -> None:
    from agentgraph.server.cli_api import cli_meta

    connector = MagicMock()
    connector.source = "rss"
    connector.url_patterns = ["https://static.example.com/*"]
    connector.observation_url_patterns = AsyncMock()
    settings = MagicMock(dwell_threshold_seconds=3)

    with (
        patch("agentgraph.connectors.registry.get_all_connectors", return_value=[connector]),
        patch("agentgraph.config.get_settings", return_value=settings),
    ):
        result = await cli_meta(include_dynamic_url_patterns=False)

    assert result["entity_types"]
    assert result["platforms"] == ["rss"]
    assert result["url_patterns"] == ["https://static.example.com/*"]
    connector.observation_url_patterns.assert_not_awaited()


@pytest.mark.asyncio
async def test_cli_meta_skips_slow_dynamic_connector_and_returns_remaining_patterns() -> None:
    from agentgraph.server.cli_api import cli_meta

    slow_connector = MagicMock()
    slow_connector.source = "rss"

    async def slow_patterns() -> list[str]:
        await asyncio.sleep(3)
        return ["https://slow.example.com/*"]

    slow_connector.observation_url_patterns = slow_patterns
    fast_connector = MagicMock()
    fast_connector.source = "web"
    fast_connector.observation_url_patterns = AsyncMock(return_value=["http://localhost:3000/*"])
    settings = MagicMock(dwell_threshold_seconds=3)

    with (
        patch("agentgraph.connectors.registry.get_all_connectors", return_value=[slow_connector, fast_connector]),
        patch("agentgraph.config.get_settings", return_value=settings),
        patch("agentgraph.server.cli_api._DYNAMIC_PATTERN_TIMEOUT_SECONDS", 0.01),
    ):
        result = await cli_meta()

    assert result["url_patterns"] == ["http://localhost:3000/*"]


@pytest.mark.asyncio
async def test_rss_dwell_uses_exact_observation_reference() -> None:
    from agentgraph.server.dwell import record_dwell_time

    backend = MagicMock()
    backend.upsert_stub_entity = AsyncMock()
    backend.record_observation = AsyncMock()
    set_backend(backend)
    ref = SourceReference(
        source="rss",
        resource_type="document",
        resource_id="entry/known",
        fetch_meta={"web_url": "https://example.com/articles/known"},
    )
    settings = MagicMock(dwell_threshold_seconds=60)

    with (
        patch("agentgraph.server.dwell.classify_observation_url", new=AsyncMock(return_value=ref)),
        patch("agentgraph.config.get_settings", return_value=settings),
    ):
        result = await record_dwell_time("https://example.com/articles/known", 15_000)

    assert result == {"status": "accepted", "source": "rss", "resource_type": "document"}
    backend.upsert_stub_entity.assert_awaited_once_with("Document", "rss", "entry/known")
    backend.record_observation.assert_awaited_once_with("rss", "entry/known", 15_000)


@pytest.mark.asyncio
async def test_dwell_passes_metadata_to_observation_resolution() -> None:
    from agentgraph.server.dwell import record_dwell_time

    backend = MagicMock()
    backend.upsert_stub_entity = AsyncMock()
    backend.record_observation = AsyncMock()
    set_backend(backend)
    ref = SourceReference(source="gmail", resource_type="thread", resource_id="api-thread")
    settings = MagicMock(dwell_threshold_seconds=60)
    meta = {"gmail_thread_id": "api-thread"}

    with (
        patch("agentgraph.server.dwell.classify_observation_url", new=AsyncMock(return_value=ref)) as classify,
        patch("agentgraph.config.get_settings", return_value=settings),
    ):
        result = await record_dwell_time("https://mail.google.com/mail/u/0/#inbox/opaque", 15_000, meta)

    assert result["status"] == "accepted"
    classify.assert_awaited_once_with(
        "https://mail.google.com/mail/u/0/#inbox/opaque",
        meta=meta,
    )
    backend.upsert_stub_entity.assert_awaited_once_with("Email", "gmail", "api-thread")


@pytest.mark.asyncio
async def test_dwell_dispatch_upserts_returned_batch() -> None:
    from agentgraph.server.dwell import _dispatch  # pyright: ignore[reportPrivateUsage]

    batch = EntityBatch(
        entities=[
            EntityRecord(
                entity_type="Document",
                platform="rss",
                platform_entity_id="entry/known",
                content="Hydrated article",
            )
        ]
    )
    connector = MagicMock()
    connector.fetch = AsyncMock(return_value=batch)

    with (
        patch("agentgraph.connectors.registry.get_connector", return_value=connector),
        patch("agentgraph.graph.upsert.upsert_batch", new=AsyncMock()) as upsert_batch,
    ):
        await _dispatch(
            "rss",
            "document",
            "entry/known",
            {"web_url": "https://example.com/articles/known"},
        )

    connector.fetch.assert_awaited_once_with(
        resource_type="document",
        resource_id="entry/known",
        meta={"web_url": "https://example.com/articles/known"},
    )
    upsert_batch.assert_awaited_once_with(batch)
