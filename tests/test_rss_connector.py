"""Unit tests for the RSS connector."""

from __future__ import annotations

from unittest.mock import patch

import feedparser  # type: ignore[import-untyped]
import pytest
from agentgraph_connector_rss import RssConnector, _fetch_feed
from agentgraph_connector_rss.auth import (
    RssCredentials,
    add_feed_urls,
    list_rss_accounts,
    verify_rss_auth,
)


def test_rss_can_handle_configured_feed_urls() -> None:
    connector = RssConnector()

    with patch(
        "agentgraph_connector_rss.load_rss_creds",
        return_value=RssCredentials(feed_urls=["https://example.com/feed.xml"]),
    ):
        assert connector.can_handle("https://example.com/feed.xml")
        assert not connector.can_handle("http://example.com/rss")


def test_rss_can_handle_returns_false_without_config() -> None:
    connector = RssConnector()

    with patch("agentgraph_connector_rss.load_rss_creds", side_effect=RuntimeError("missing")):
        assert not connector.can_handle("https://example.com/feed.xml")
    assert not connector.can_handle("file:///tmp/feed.xml")


def test_list_rss_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_load_platform_accounts(platform: str) -> list[dict[str, object]]:
        assert platform == "rss"
        return [
            {
                "account_id": "rss-main",
                "feed_urls": ["https://example.com/feed.xml"],
                "label": "My Feeds",
            }
        ]

    monkeypatch.setattr(
        "agentgraph.auth.credentials.load_platform_accounts",
        fake_load_platform_accounts,
    )

    assert list_rss_accounts() == [
        {
            "account_id": "rss-main",
            "label": "My Feeds",
            "feed_count": "1",
        }
    ]


def test_add_feed_urls_creates_rss_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: dict[str, object] = {}

    monkeypatch.setattr("agentgraph_connector_rss.auth.list_rss_accounts", lambda: [])
    monkeypatch.setattr("agentgraph_connector_rss.auth.load_rss_creds", lambda account_id=None: (_ for _ in ()).throw(RuntimeError("missing")))
    monkeypatch.setattr(
        "agentgraph.auth.credentials.save_platform",
        lambda platform, data: saved.update({"platform": platform, "data": data}),
    )

    creds = add_feed_urls(["https://example.com/feed.xml"])

    assert creds.feed_urls == ["https://example.com/feed.xml"]
    assert saved["platform"] == "rss"
    assert saved["data"] == {
        "feed_urls": ["https://example.com/feed.xml"],
        "account_id": "rss",
        "label": "RSS",
    }


@pytest.mark.asyncio
async def test_verify_rss_auth_missing() -> None:
    with patch("agentgraph_connector_rss.auth.load_rss_creds", side_effect=RuntimeError("missing")):
        assert await verify_rss_auth() == ("missing", None)


@pytest.mark.asyncio
async def test_verify_rss_auth_requires_feed_urls() -> None:
    with patch(
        "agentgraph_connector_rss.auth.load_rss_creds",
        return_value=RssCredentials(feed_urls=[]),
    ):
        assert await verify_rss_auth() == ("invalid", "No RSS feed URLs configured")


@pytest.mark.asyncio
async def test_verify_rss_auth_uses_feed_preview() -> None:
    with (
        patch(
            "agentgraph_connector_rss.auth.load_rss_creds",
            return_value=RssCredentials(feed_urls=["https://example.com/feed.xml"]),
        ),
        patch(
            "agentgraph_connector_rss.auth.preview_feed",
            return_value={"entries": [{"title": "One"}], "bozo": False},
        ) as preview,
    ):
        status = await verify_rss_auth("rss-main")

    assert status == ("ok", "1 feed(s), sample returned 1 article(s)")
    preview.assert_awaited_once_with("https://example.com/feed.xml", count=1)


@pytest.mark.asyncio
async def test_fetch_feed_maps_entries_to_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Parsed:
        bozo = False
        feed = {"title": "Example Feed"}
        entries = [
            {
                "id": "post-1",
                "title": "First Post",
                "link": "https://example.com/first",
                "summary": "A short summary",
                "published": "Fri, 05 Jun 2026 10:00:00 GMT",
                "author": "Author Name",
            }
        ]

    def fake_parse(feed_url: str) -> _Parsed:
        assert feed_url == "https://example.com/feed.xml"
        return _Parsed()

    monkeypatch.setattr(feedparser, "parse", fake_parse)

    batch = await _fetch_feed("https://example.com/feed.xml")

    assert len(batch.entities) == 2
    feed = batch.entities[0]
    entry = batch.entities[1]
    assert feed.entity_type == "Folder"
    assert feed.title == "Example Feed"
    assert entry.entity_type == "Document"
    assert entry.platform == "rss"
    assert entry.title == "First Post"
    assert entry.content and "A short summary" in entry.content
    assert entry.metadata["link"] == "https://example.com/first"
    assert batch.edges[0].edge_type == "posted_in"
