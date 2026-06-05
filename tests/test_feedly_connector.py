"""Unit tests for the Feedly connector auth slice."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from agentgraph_connector_feedly import FeedlyConnector
from agentgraph_connector_feedly.auth import (
    FeedlyCredentials,
    collect_stream_preview,
    list_feedly_accounts,
    verify_feedly_auth,
)

from agentgraph.connectors.base import EntityBatch


def test_feedly_can_handle() -> None:
    connector = FeedlyConnector()

    assert connector.can_handle("https://feedly.com/i/my")
    assert connector.can_handle("https://api.feedly.com/v3/streams/contents")
    assert not connector.can_handle("https://example.com")


@pytest.mark.asyncio
async def test_feedly_fetch_noops_until_ingestion_model_is_chosen() -> None:
    batch = await FeedlyConnector().fetch("document", "article-id")

    assert batch == EntityBatch()


def test_list_feedly_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agentgraph.auth.credentials.load_platform_accounts",
        lambda platform: [
            {
                "account_id": "feedly-main",
                "access_token": "fe_123",
                "stream_ids": ["enterprise/acme/category/abc"],
                "label": "Acme Feedly",
            }
        ],
    )

    assert list_feedly_accounts() == [
        {
            "account_id": "feedly-main",
            "label": "Acme Feedly",
            "stream_count": "1",
        }
    ]


@pytest.mark.asyncio
async def test_verify_feedly_auth_missing() -> None:
    with patch("agentgraph_connector_feedly.auth.load_feedly_creds", side_effect=RuntimeError("missing")):
        assert await verify_feedly_auth() == ("missing", None)


@pytest.mark.asyncio
async def test_verify_feedly_auth_requires_streams() -> None:
    with patch(
        "agentgraph_connector_feedly.auth.load_feedly_creds",
        return_value=FeedlyCredentials(access_token="fe_123", stream_ids=[]),
    ):
        assert await verify_feedly_auth() == ("invalid", "No Feedly stream IDs configured")


@pytest.mark.asyncio
async def test_verify_feedly_auth_uses_stream_preview() -> None:
    with (
        patch(
            "agentgraph_connector_feedly.auth.load_feedly_creds",
            return_value=FeedlyCredentials(access_token="fe_123", stream_ids=["stream-1"]),
        ),
        patch(
            "agentgraph_connector_feedly.auth.collect_stream_preview",
            new=AsyncMock(return_value={"items": [{"title": "One"}]}),
        ) as preview,
    ):
        status = await verify_feedly_auth("feedly-main")

    assert status == ("ok", "1 stream(s), sample returned 1 article(s)")
    preview.assert_awaited_once_with("stream-1", account_id="feedly-main", count=1)


@pytest.mark.asyncio
async def test_verify_feedly_auth_marks_unauthorized_invalid() -> None:
    request = httpx.Request("GET", "https://api.feedly.com/v3/streams/contents")
    response = httpx.Response(401, request=request)
    error = httpx.HTTPStatusError("unauthorized", request=request, response=response)

    with (
        patch(
            "agentgraph_connector_feedly.auth.load_feedly_creds",
            return_value=FeedlyCredentials(access_token="fe_123", stream_ids=["stream-1"]),
        ),
        patch("agentgraph_connector_feedly.auth.collect_stream_preview", side_effect=error),
    ):
        assert await verify_feedly_auth() == ("invalid", "Feedly rejected credentials (401)")


@pytest.mark.asyncio
async def test_collect_stream_preview_calls_feedly_api(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"items": [{"title": "Sample"}]}

    class _FakeClient:
        def __init__(self, timeout: int) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(
            self,
            url: str,
            *,
            headers: dict[str, str],
            params: dict[str, str],
        ) -> _FakeResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["params"] = params
            return _FakeResponse()

    monkeypatch.setattr(
        "agentgraph_connector_feedly.auth.load_feedly_creds",
        lambda account_id=None: FeedlyCredentials(access_token="fe_123", stream_ids=["stream-1"]),
    )
    monkeypatch.setattr("agentgraph_connector_feedly.auth.httpx.AsyncClient", _FakeClient)

    result = await collect_stream_preview("stream-1", account_id="feedly-main", count=250)

    assert result == {"items": [{"title": "Sample"}]}
    assert captured["url"] == "https://api.feedly.com/v3/streams/contents"
    assert captured["headers"] == {"Authorization": "Bearer fe_123"}
    assert captured["params"] == {"streamID": "stream-1", "count": "100"}
