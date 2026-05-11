"""Unit tests for Google Docs and Slack connectors (mocked HTTP)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from agentgraph_connector_google.gdocs import GoogleDocsConnector, _fetch_doc
from agentgraph_connector_google.gdrive import _fetch_drive_file
from agentgraph_connector_slack import SlackConnector, _parse_mentions

from agentgraph.connectors.base import EntityBatch

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _recent_dt() -> datetime:
    from datetime import timedelta
    return datetime.now(UTC) - timedelta(seconds=60)


def _stale_dt() -> datetime:
    from datetime import timedelta
    return datetime.now(UTC) - timedelta(seconds=3600)


class _FakeDriveRequest:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def execute(self) -> object:
        return self._payload


class _FakeDriveFiles:
    def __init__(self, meta: dict[str, object], exported: bytes | None = None) -> None:
        self._meta = meta
        self._exported = exported or b""

    def get(self, *, fileId: str, fields: str) -> _FakeDriveRequest:  # noqa: N803
        return _FakeDriveRequest(self._meta)

    def export(self, *, fileId: str, mimeType: str) -> _FakeDriveRequest:  # noqa: N803
        return _FakeDriveRequest(self._exported)


class _FakeDriveService:
    def __init__(self, meta: dict[str, object], exported: bytes | None = None) -> None:
        self._files = _FakeDriveFiles(meta, exported)

    def files(self) -> _FakeDriveFiles:
        return self._files


# ---------------------------------------------------------------------------
# _parse_mentions
# ---------------------------------------------------------------------------

def test_parse_mentions_empty() -> None:
    assert _parse_mentions("hello world") == []


def test_parse_mentions_single() -> None:
    assert _parse_mentions("hey <@U123ABC>!") == ["U123ABC"]


def test_parse_mentions_multiple() -> None:
    result = _parse_mentions("<@UA1> and <@UB2> discussed it")
    assert result == ["UA1", "UB2"]


def test_parse_mentions_no_false_positives() -> None:
    assert _parse_mentions("<#CABC|general>") == []


# ---------------------------------------------------------------------------
# GoogleDocsConnector.fetch — FetchPolicy branching (no real Google API)
# ---------------------------------------------------------------------------

@pytest.fixture
def gdocs_connector() -> GoogleDocsConnector:
    return GoogleDocsConnector()


@pytest.mark.asyncio
async def test_gdocs_fetch_fresh_returns_empty_batch(gdocs_connector: GoogleDocsConnector) -> None:
    """When data is fresh, connector returns empty batch and touches last_accessed."""
    with (
        patch.object(gdocs_connector, "last_synced_at", new=AsyncMock(return_value=_recent_dt())),
        patch("agentgraph_connector_google.gdocs._touch_last_accessed", new=AsyncMock()) as mock_touch,
    ):
        batch = await gdocs_connector.fetch("document", "doc-abc")

    assert batch == EntityBatch()
    mock_touch.assert_awaited_once_with("doc-abc")


@pytest.mark.asyncio
async def test_gdocs_fetch_stale_calls_fetch_doc(gdocs_connector: GoogleDocsConnector) -> None:
    """When data is stale, connector calls _fetch_doc and upserts the batch."""
    fake_batch = EntityBatch()
    with (
        patch.object(gdocs_connector, "last_synced_at", new=AsyncMock(return_value=_stale_dt())),
        patch("agentgraph_connector_google.gdocs._fetch_doc", new=AsyncMock(return_value=fake_batch)),
        patch("agentgraph_connector_google.gdocs.upsert_batch", new=AsyncMock()) as mock_upsert,
    ):
        batch = await gdocs_connector.fetch("document", "doc-xyz")

    assert batch is fake_batch
    mock_upsert.assert_awaited_once_with(fake_batch)


@pytest.mark.asyncio
async def test_gdocs_fetch_first_visit_calls_fetch_doc(gdocs_connector: GoogleDocsConnector) -> None:
    """On first visit (no sync), connector calls _fetch_doc."""
    fake_batch = EntityBatch()
    with (
        patch.object(gdocs_connector, "last_synced_at", new=AsyncMock(return_value=None)),
        patch("agentgraph_connector_google.gdocs._fetch_doc", new=AsyncMock(return_value=fake_batch)),
        patch("agentgraph_connector_google.gdocs.upsert_batch", new=AsyncMock()),
    ):
        batch = await gdocs_connector.fetch("document", "doc-new")

    assert batch is fake_batch


@pytest.mark.asyncio
async def test_gdocs_fetch_doc_adds_download_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agentgraph_connector_google.gdocs._build_drive_service",
        lambda: _FakeDriveService(
            {
                "name": "Tax Return 2025",
                "owners": [{"emailAddress": "owner@example.com", "displayName": "Owner"}],
            },
            b"<html><body><h1>Tax Return 2025</h1></body></html>",
        ),
    )

    batch = await _fetch_doc("doc-123")

    assert batch.entities
    entity = batch.entities[0]
    assert entity.metadata["mime_type"] == "text/html"
    assert entity.metadata["download_url"].endswith("/export?mimeType=text/html")
    assert entity.metadata["web_url"] == "https://docs.google.com/document/d/doc-123/view"


@pytest.mark.asyncio
async def test_drive_file_fetch_adds_download_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agentgraph_connector_google.gdrive._build_drive_service",
        lambda: _FakeDriveService(
            {
                "name": "Tax Return 2025.pdf",
                "mimeType": "application/pdf",
                "webViewLink": "https://drive.google.com/file/d/file-123/view",
                "webContentLink": "https://drive.google.com/uc?id=file-123&export=download",
                "owners": [{"emailAddress": "owner@example.com", "displayName": "Owner"}],
            }
        ),
    )

    batch = await _fetch_drive_file("file-123")

    assert batch.entities
    entity = batch.entities[0]
    assert entity.platform == "gdrive"
    assert entity.metadata["mime_type"] == "application/pdf"
    assert entity.metadata["download_url"] == "https://drive.google.com/uc?id=file-123&export=download"
    assert entity.metadata["web_url"] == "https://drive.google.com/file/d/file-123/view"


# ---------------------------------------------------------------------------
# SlackConnector.fetch — FetchPolicy branching (no real Slack API)
# ---------------------------------------------------------------------------

@pytest.fixture
def slack_connector() -> SlackConnector:
    return SlackConnector()


@pytest.mark.asyncio
async def test_slack_fetch_fresh_returns_empty_batch(slack_connector: SlackConnector) -> None:
    """When channel data is fresh, connector returns empty batch."""
    with (
        patch.object(slack_connector, "last_synced_at", new=AsyncMock(return_value=_recent_dt())),
        patch("agentgraph_connector_slack._touch_last_accessed", new=AsyncMock()) as mock_touch,
    ):
        batch = await slack_connector.fetch("channel", "C12345")

    assert batch == EntityBatch()
    mock_touch.assert_awaited_once_with("C12345")


@pytest.mark.asyncio
async def test_slack_fetch_stale_calls_fetch_channel(slack_connector: SlackConnector) -> None:
    """When channel data is stale, connector calls _fetch_channel with oldest= param."""
    stale_time = _stale_dt()
    fake_batch = EntityBatch()
    with (
        patch.object(slack_connector, "last_synced_at", new=AsyncMock(return_value=stale_time)),
        patch("agentgraph_connector_slack._fetch_channel", new=AsyncMock(return_value=fake_batch)) as mock_fetch,
        patch("agentgraph_connector_slack.upsert_batch", new=AsyncMock()),
    ):
        batch = await slack_connector.fetch("channel", "C12345")

    assert batch is fake_batch
    mock_fetch.assert_awaited_once_with("C12345", oldest=str(stale_time.timestamp()))


@pytest.mark.asyncio
async def test_slack_fetch_first_visit_calls_fetch_channel_no_oldest(slack_connector: SlackConnector) -> None:
    """On first visit, _fetch_channel called with oldest=None."""
    fake_batch = EntityBatch()
    with (
        patch.object(slack_connector, "last_synced_at", new=AsyncMock(return_value=None)),
        patch("agentgraph_connector_slack._fetch_channel", new=AsyncMock(return_value=fake_batch)) as mock_fetch,
        patch("agentgraph_connector_slack.upsert_batch", new=AsyncMock()),
    ):
        await slack_connector.fetch("channel", "C99999")

    mock_fetch.assert_awaited_once_with("C99999", oldest=None)


# ---------------------------------------------------------------------------
# can_handle routing
# ---------------------------------------------------------------------------

def test_gdocs_can_handle(gdocs_connector: GoogleDocsConnector) -> None:
    assert gdocs_connector.can_handle("https://docs.google.com/document/d/abc123/edit")
    assert not gdocs_connector.can_handle("https://slack.com")


def test_slack_can_handle(slack_connector: SlackConnector) -> None:
    assert slack_connector.can_handle("https://app.slack.com/client/T123/C456")
    assert not slack_connector.can_handle("https://docs.google.com")
