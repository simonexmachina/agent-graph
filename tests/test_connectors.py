"""Unit tests for Google Docs and Slack connectors (mocked HTTP)."""

from __future__ import annotations

# pyright: reportPrivateUsage=false
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from agentgraph_connector_google.gdocs import GoogleDocsConnector, _fetch_doc
from agentgraph_connector_google.gdrive import DriveChangesConnector, _fetch_drive_file
from agentgraph_connector_google.gmail import GmailConnector, _thread_to_items
from agentgraph_connector_google.gsheets import GoogleSheetsConnector
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

    def get_media(self, *, fileId: str) -> _FakeDriveRequest:  # noqa: N803
        return _FakeDriveRequest(self._exported)


class _FakeDriveService:
    def __init__(self, meta: dict[str, object], exported: bytes | None = None) -> None:
        self._files = _FakeDriveFiles(meta, exported)

    def files(self) -> _FakeDriveFiles:
        return self._files


class _FakeMediaIoBaseDownload:
    def __init__(self, fd: Any, request: _FakeDriveRequest) -> None:
        self._fd = fd
        self._request = request

    def next_chunk(self) -> tuple[None, bool]:
        self._fd.write(self._request.execute())
        return None, True


class _FakeGmailRequest:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def execute(self) -> object:
        return self._payload


class _FakeGmailAttachments:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def get(self, *, userId: str, messageId: str, id: str) -> _FakeGmailRequest:  # noqa: N803, A002
        return _FakeGmailRequest(self._payload)


class _FakeGmailMessages:
    def __init__(self, payload: dict[str, object]) -> None:
        self._attachments = _FakeGmailAttachments(payload)

    def attachments(self) -> _FakeGmailAttachments:
        return self._attachments


class _FakeGmailUsers:
    def __init__(self, payload: dict[str, object]) -> None:
        self._messages = _FakeGmailMessages(payload)

    def messages(self) -> _FakeGmailMessages:
        return self._messages


class _FakeGmailService:
    def __init__(self, payload: dict[str, object]) -> None:
        self._users = _FakeGmailUsers(payload)

    def users(self) -> _FakeGmailUsers:
        return self._users


class _FakeBackend:
    async def get_entity_by_platform(self, platform: str, platform_entity_id: str) -> dict[str, object]:
        return {
            "platform": platform,
            "platform_entity_id": platform_entity_id,
            "metadata": {
                "filename": "approval.pdf",
                "mime_type": "application/pdf",
                "account_id": "simon@example.com",
            },
        }


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
    assert entity.metadata["content_type"] == "text/markdown"
    assert entity.metadata["mime_type"] == "text/html"
    download_url = entity.metadata["download_url"]
    assert isinstance(download_url, str)
    assert download_url.endswith("/export?mimeType=text/html")
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


@pytest.mark.asyncio
async def test_drive_file_download_uses_google_auth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "agentgraph_connector_google.gdrive._build_drive_service",
        lambda: _FakeDriveService(
            {
                "name": "Tax Return 2025.pdf",
                "mimeType": "application/pdf",
                "size": "7",
            },
            b"pdfdata",
        ),
    )
    monkeypatch.setattr("googleapiclient.http.MediaIoBaseDownload", _FakeMediaIoBaseDownload)

    result = await DriveChangesConnector().download("document", "file-123", str(tmp_path))

    assert result["path"] == str(tmp_path / "Tax Return 2025.pdf")
    assert result["bytes"] == 7
    assert result["mime_type"] == "application/pdf"
    assert (tmp_path / "Tax Return 2025.pdf").read_bytes() == b"pdfdata"


@pytest.mark.asyncio
async def test_gdocs_download_delegates_to_drive(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_download = AsyncMock(return_value={"path": "/tmp/doc.docx"})
    monkeypatch.setattr("agentgraph_connector_google.gdrive.download_drive_file", fake_download)

    result = await GoogleDocsConnector().download("document", "doc-123", "/tmp")

    assert result["path"] == "/tmp/doc.docx"
    fake_download.assert_awaited_once_with("doc-123", "/tmp")


@pytest.mark.asyncio
async def test_gsheets_download_delegates_to_drive(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_download = AsyncMock(return_value={"path": "/tmp/sheet.xlsx"})
    monkeypatch.setattr("agentgraph_connector_google.gdrive.download_drive_file", fake_download)

    result = await GoogleSheetsConnector().download("spreadsheet", "sheet-123", "/tmp")

    assert result["path"] == "/tmp/sheet.xlsx"
    fake_download.assert_awaited_once_with("sheet-123", "/tmp")


# ---------------------------------------------------------------------------
# SlackConnector.fetch — FetchPolicy branching (no real Slack API)
# ---------------------------------------------------------------------------

@pytest.fixture
def slack_connector() -> SlackConnector:
    return SlackConnector()


@pytest.fixture
def gmail_connector() -> GmailConnector:
    return GmailConnector()


@pytest.mark.asyncio
async def test_slack_fetch_fresh_returns_empty_batch(slack_connector: SlackConnector) -> None:
    """When channel data is fresh, connector returns empty batch."""
    with (
        patch.object(slack_connector, "last_synced_at", new=AsyncMock(return_value=_recent_dt())),
        patch("agentgraph_connector_slack._touch_last_accessed", new=AsyncMock()) as mock_touch,
    ):
        batch = await slack_connector.fetch("channel", "T123/C12345")

    assert batch == EntityBatch()
    mock_touch.assert_awaited_once_with("T123/C12345")


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
        batch = await slack_connector.fetch("channel", "T123/C12345")

    assert batch is fake_batch
    mock_fetch.assert_awaited_once_with("T123/C12345", oldest=str(stale_time.timestamp()), account_id=None)


@pytest.mark.asyncio
async def test_slack_fetch_first_visit_calls_fetch_channel_no_oldest(slack_connector: SlackConnector) -> None:
    """On first visit, _fetch_channel called with oldest=None."""
    fake_batch = EntityBatch()
    with (
        patch.object(slack_connector, "last_synced_at", new=AsyncMock(return_value=None)),
        patch("agentgraph_connector_slack._fetch_channel", new=AsyncMock(return_value=fake_batch)) as mock_fetch,
        patch("agentgraph_connector_slack.upsert_batch", new=AsyncMock()),
    ):
        await slack_connector.fetch("channel", "T123/C99999")

    mock_fetch.assert_awaited_once_with("T123/C99999", oldest=None, account_id=None)


# ---------------------------------------------------------------------------
# can_handle routing
# ---------------------------------------------------------------------------

def test_gdocs_can_handle(gdocs_connector: GoogleDocsConnector) -> None:
    assert gdocs_connector.can_handle("https://docs.google.com/document/d/abc123/edit")
    assert not gdocs_connector.can_handle("https://slack.com")


def test_gmail_entity_url_uses_popout_view(gmail_connector: GmailConnector) -> None:
    assert (
        gmail_connector.entity_url("18f0c1d2e3a4b5c6")
        == "https://mail.google.com/mail/u/0/#all/18f0c1d2e3a4b5c6"
    )


def test_gmail_thread_to_items_adds_attachment_document_stubs() -> None:
    thread = {
        "id": "19ec9bf00171a35e",
        "messages": [
            {
                "id": "19ec9bf00171a35f",
                "labelIds": ["INBOX"],
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Variation Approval"},
                        {"name": "From", "value": "Stephanie <steph@example.com>"},
                        {"name": "To", "value": "Simon <simon@example.com>"},
                        {"name": "Date", "value": "Mon, 15 Jun 2026 15:26:00 +1000"},
                    ],
                    "parts": [
                        {
                            "filename": "Lot 10 Variation.pdf",
                            "mimeType": "application/pdf",
                            "headers": [
                                {
                                    "name": "Content-Disposition",
                                    "value": 'attachment; filename="Lot 10 Variation.pdf"',
                                }
                            ],
                            "body": {"attachmentId": "ANGjdJ8", "size": 12345},
                        },
                        {
                            "filename": "logo.png",
                            "mimeType": "image/png",
                            "headers": [
                                {"name": "Content-Disposition", "value": "inline"},
                                {"name": "Content-ID", "value": "<logo>"},
                            ],
                            "body": {"attachmentId": "INLINE123", "size": 99},
                        },
                        {
                            "mimeType": "application/octet-stream",
                            "body": {"attachmentId": "UNNAMED123", "size": 42},
                        },
                    ],
                },
            }
        ],
    }

    entity, _persons, edges, attachment_stubs = _thread_to_items(
        thread,
        account_id="simon@example.com",
    )

    assert entity is not None
    assert len(attachment_stubs) == 1
    attachment = attachment_stubs[0]
    assert attachment.entity_type == "Document"
    assert attachment.platform == "gmail"
    assert attachment.platform_entity_id == "attachment/19ec9bf00171a35f/ANGjdJ8"
    assert attachment.title == "Lot 10 Variation.pdf"
    assert attachment.is_stub is True
    assert attachment.metadata["gmail_thread_id"] == "19ec9bf00171a35e"
    assert attachment.metadata["gmail_message_id"] == "19ec9bf00171a35f"
    assert attachment.metadata["gmail_attachment_id"] == "ANGjdJ8"
    assert attachment.metadata["mime_type"] == "application/pdf"
    assert attachment.metadata["filename"] == "Lot 10 Variation.pdf"
    assert attachment.metadata["account_id"] == "simon@example.com"
    assert any(
        edge.edge_type == "references"
        and edge.source_platform_entity_id == "19ec9bf00171a35e"
        and edge.target_platform_entity_id == "attachment/19ec9bf00171a35f/ANGjdJ8"
        and edge.platform == "gmail"
        for edge in edges
    )


@pytest.mark.asyncio
async def test_gmail_download_attachment_document_stub(
    gmail_connector: GmailConnector,
    tmp_path: Path,
) -> None:
    encoded = "YXBwcm92YWw"  # b"approval" without base64 padding
    with (
        patch(
            "agentgraph_connector_google.gmail._build_service_for",
            return_value=_FakeGmailService({"data": encoded}),
        ) as build_service,
        patch("agentgraph.core.context.get_backend", return_value=_FakeBackend()),
    ):
        result = await gmail_connector.download(
            "document",
            "attachment/19ec9bf00171a35f/ANGjdJ8",
            str(tmp_path),
        )

    assert Path(result["path"]).read_bytes() == b"approval"
    assert result["filename"] == "approval.pdf"
    assert result["bytes"] == 8
    assert result["platform"] == "gmail"
    assert result["platform_entity_id"] == "attachment/19ec9bf00171a35f/ANGjdJ8"
    assert result["mime_type"] == "application/pdf"
    build_service.assert_called_once_with("simon@example.com")


def test_slack_can_handle(slack_connector: SlackConnector) -> None:
    assert slack_connector.can_handle("https://app.slack.com/client/T123/C456")
    assert not slack_connector.can_handle("https://docs.google.com")


@pytest.mark.asyncio
async def test_gmail_fetch_uses_meta_thread_id(gmail_connector: GmailConnector) -> None:
    fake_batch = EntityBatch()
    with (
        patch("agentgraph_connector_google.gmail._fetch_thread_by_thread_id", new=AsyncMock(return_value=fake_batch)) as mock_fetch,
        patch("agentgraph_connector_google.gmail.upsert_batch", new=AsyncMock()) as mock_upsert,
    ):
        batch = await gmail_connector.fetch(
            "thread",
            "FMfcgzQgLXnVJSqVLPfFQTLVZqtCZDvb",
            meta={"gmail_thread_id": "19e63ac7401ac0fe"},
        )

    assert batch is fake_batch
    mock_fetch.assert_awaited_once_with(
        "19e63ac7401ac0fe",
        account_id=None,
    )
    mock_upsert.assert_awaited_once_with(fake_batch)
