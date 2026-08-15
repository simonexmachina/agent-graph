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
    resp = client.post(
        "/report-dwell",
        json={
            "url": "https://example.com/unknown",
            "dwell_ms": 15000,
            "observation_id": "34b2ad4d-55e3-4599-bf35-1e258a704bcd",
            "observed": True,
        },
    )
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
    backend.observation_exists = AsyncMock(return_value=True)
    set_backend(backend)
    ref = SourceReference(
        source="rss",
        resource_type="document",
        resource_id="entry/known",
        fetch_meta={"web_url": "https://example.com/articles/known"},
    )
    with (
        patch("agentgraph.server.dwell.classify_observation_url", new=AsyncMock(return_value=ref)),
    ):
        result = await record_dwell_time(
            "https://example.com/articles/known",
            15_000,
            "observation-1",
            True,
        )

    assert result == {
        "status": "accepted",
        "source": "rss",
        "resource_type": "document",
        "observation_created": False,
    }
    backend.upsert_stub_entity.assert_not_called()


@pytest.mark.asyncio
async def test_dwell_passes_metadata_to_observation_resolution() -> None:
    from agentgraph.server.dwell import record_dwell_time

    backend = MagicMock()
    backend.increment_dwell_time = AsyncMock()
    set_backend(backend)
    ref = SourceReference(source="gmail", resource_type="thread", resource_id="api-thread")
    meta = {"gmail_thread_id": "api-thread"}

    with (
        patch("agentgraph.server.dwell.classify_observation_url", new=AsyncMock(return_value=ref)) as classify,
    ):
        result = await record_dwell_time(
            "https://mail.google.com/mail/u/0/#inbox/opaque",
            15_000,
            "observation-2",
            False,
            meta,
        )

    assert result["status"] == "accepted"
    classify.assert_awaited_once_with(
        "https://mail.google.com/mail/u/0/#inbox/opaque",
        meta=meta,
    )
    backend.upsert_stub_entity.assert_not_called()
    backend.increment_dwell_time.assert_awaited_once_with("gmail", "api-thread", 15_000)


@pytest.mark.asyncio
async def test_new_observation_dispatches_once() -> None:
    from agentgraph.server.dwell import record_dwell_time

    backend = MagicMock()
    backend.observation_exists = AsyncMock(side_effect=[False, True])
    backend.get_entity_by_platform = AsyncMock(return_value={"id": "thread-entity"})
    backend.record_observation_once = AsyncMock(return_value=True)
    set_backend(backend)
    ref = SourceReference(source="gmail", resource_type="thread", resource_id="thread-1")

    with (
        patch("agentgraph.server.dwell.classify_observation_url", new=AsyncMock(return_value=ref)),
        patch(
            "agentgraph.server.dwell._dispatch",
            new=AsyncMock(return_value={"entities": 1, "persons": 0, "edges": 0}),
        ) as dispatch,
    ):
        first = await record_dwell_time(
            "https://mail.google.com/thread-1", 3000, "observation-1", True
        )
        duplicate = await record_dwell_time(
            "https://mail.google.com/thread-1", 3000, "observation-1", True
        )
    assert first["observation_created"] is True
    assert first["fetch"] == {"entities": 1, "persons": 0, "edges": 0}
    assert duplicate["observation_created"] is False
    dispatch.assert_awaited_once_with("gmail", "thread", "thread-1", None)
    backend.record_observation_once.assert_awaited_once_with(
        "gmail",
        "thread-1",
        "observation-1",
        "https://mail.google.com/thread-1",
        3000,
    )
    backend.upsert_stub_entity.assert_not_called()


@pytest.mark.asyncio
async def test_concurrent_duplicate_observation_awaits_one_fetch() -> None:
    from agentgraph.server.dwell import record_dwell_time

    backend = MagicMock()
    backend.observation_exists = AsyncMock(return_value=False)
    backend.get_entity_by_platform = AsyncMock(return_value={"id": "thread-entity"})
    backend.record_observation_once = AsyncMock(return_value=True)
    set_backend(backend)
    ref = SourceReference(source="gmail", resource_type="thread", resource_id="thread-1")
    fetch_started = asyncio.Event()
    release_fetch = asyncio.Event()

    async def dispatch(*_: object, **__: object) -> dict[str, int]:
        fetch_started.set()
        await release_fetch.wait()
        return {"entities": 1, "persons": 0, "edges": 0}

    with (
        patch("agentgraph.server.dwell.classify_observation_url", new=AsyncMock(return_value=ref)),
        patch("agentgraph.server.dwell._dispatch", side_effect=dispatch) as mocked_dispatch,
    ):
        first_task = asyncio.create_task(
            record_dwell_time("https://mail.google.com/thread-1", 3000, "observation-1", True)
        )
        await fetch_started.wait()
        duplicate_task = asyncio.create_task(
            record_dwell_time("https://mail.google.com/thread-1", 3000, "observation-1", True)
        )
        await asyncio.sleep(0)
        release_fetch.set()
        first, duplicate = await asyncio.gather(first_task, duplicate_task)

    assert first["observation_created"] is True
    assert duplicate["observation_created"] is False
    assert mocked_dispatch.await_count == 1
    backend.record_observation_once.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_observation_does_not_create_or_mark_entity() -> None:
    from agentgraph.server.dwell import ObservationFetchError, record_dwell_time

    backend = MagicMock()
    backend.observation_exists = AsyncMock(return_value=False)
    backend.record_observation_once = AsyncMock()
    set_backend(backend)
    ref = SourceReference(source="gdrive", resource_type="folder", resource_id="folder-1")

    with (
        patch("agentgraph.server.dwell.classify_observation_url", new=AsyncMock(return_value=ref)),
        patch(
            "agentgraph.server.dwell._dispatch",
            new=AsyncMock(side_effect=ObservationFetchError("Drive unavailable")),
        ),
        pytest.raises(ObservationFetchError, match="Drive unavailable"),
    ):
        await record_dwell_time(
            "https://drive.google.com/drive/folders/folder-1",
            3000,
            "observation-1",
            True,
        )

    backend.upsert_stub_entity.assert_not_called()
    backend.record_observation_once.assert_not_awaited()


@pytest.mark.asyncio
async def test_observation_rejects_fetch_without_persisted_target() -> None:
    from agentgraph.server.dwell import ObservationFetchError, record_dwell_time

    backend = MagicMock()
    backend.observation_exists = AsyncMock(return_value=False)
    backend.get_entity_by_platform = AsyncMock(return_value=None)
    backend.record_observation_once = AsyncMock()
    set_backend(backend)
    ref = SourceReference(source="gdrive", resource_type="folder", resource_id="folder-1")

    with (
        patch("agentgraph.server.dwell.classify_observation_url", new=AsyncMock(return_value=ref)),
        patch(
            "agentgraph.server.dwell._dispatch",
            new=AsyncMock(return_value={"entities": 0, "persons": 0, "edges": 0}),
        ),
        pytest.raises(ObservationFetchError, match="without persisting"),
    ):
        await record_dwell_time(
            "https://drive.google.com/drive/folders/folder-1",
            3000,
            "observation-1",
            True,
        )

    backend.record_observation_once.assert_not_awaited()


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
        result = await _dispatch(
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
    assert result == {"entities": 1, "persons": 0, "edges": 0}


def test_report_dwell_returns_bad_gateway_for_connector_failure(client: TestClient) -> None:
    from agentgraph.server.dwell import ObservationFetchError

    with patch(
        "agentgraph.server.dwell.record_dwell_time",
        new=AsyncMock(side_effect=ObservationFetchError("Connector fetch failed")),
    ):
        response = client.post(
            "/report-dwell",
            json={
                "url": "https://drive.google.com/drive/folders/folder-1",
                "dwell_ms": 3000,
                "observation_id": "34b2ad4d-55e3-4599-bf35-1e258a704bcd",
                "observed": True,
            },
        )

    assert response.status_code == 502
    assert response.json() == {"detail": "Connector fetch failed"}
