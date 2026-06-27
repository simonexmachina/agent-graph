"""Unit tests for the RSS connector."""

from __future__ import annotations

# pyright: reportPrivateUsage=false
# pyright: reportOptionalMemberAccess=false
# pyright: reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportUnknownMemberType=false
import logging
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import feedparser  # type: ignore[import-untyped]
import pytest
from agentgraph_connector_rss import RssConnector, _fetch_feed
from agentgraph_connector_rss.auth import (
    OpmlFeed,
    RssConfig,
    _checkbox_select_opml_feeds,
    add_feed_urls,
    import_opml_feeds,
    load_rss_config,
    parse_opml_feeds,
    remove_feed_urls,
    resolve_feed_source,
    save_rss_config,
    select_opml_feeds,
    verify_rss_auth,
)

from agentgraph.connectors.base import EntityRecord
from agentgraph.core.context import set_backend


class _ParsedFeed:
    version = "rss20"
    bozo = False
    bozo_exception = None
    feed = {"title": "Example Feed"}
    entries: list[dict[str, str]] = []


class _ParsedNonFeed:
    version = ""
    bozo = False
    bozo_exception = None
    feed: dict[str, str] = {}
    entries: list[dict[str, str]] = []


def test_rss_can_handle_configured_feed_urls() -> None:
    connector = RssConnector()

    with patch(
        "agentgraph_connector_rss.load_rss_settings",
        return_value=RssConfig(feed_urls=["https://example.com/feed.xml"]),
    ):
        assert connector.can_handle("https://example.com/feed.xml")
        assert not connector.can_handle("http://example.com/rss")


def test_rss_can_handle_returns_false_without_config() -> None:
    connector = RssConnector()

    with patch("agentgraph_connector_rss.load_rss_settings", side_effect=RuntimeError("missing")):
        assert not connector.can_handle("https://example.com/feed.xml")
    assert not connector.can_handle("file:///tmp/feed.xml")


def test_rss_config_roundtrip_uses_config_toml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("agentgraph.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("agentgraph.config.CONFIG_FILE", config_file)
    monkeypatch.setattr("agentgraph.config.CONFIG_YAML_FILE", tmp_path / "config.yaml")

    save_rss_config(
        RssConfig(
            feed_urls=["https://example.com/feed.xml"],
        )
    )

    assert load_rss_config() == {"feed_urls": ["https://example.com/feed.xml"]}
    rendered = config_file.read_text(encoding="utf-8")
    assert "[connectors.rss]" in rendered
    assert "[[connectors.rss.accounts]]" not in rendered
    assert 'feed_urls = ["https://example.com/feed.xml"]' in rendered


def test_rss_config_roundtrip_uses_config_yaml_when_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_file = tmp_path / "config.toml"
    config_yaml_file = tmp_path / "config.yaml"
    config_yaml_file.write_text("server:\n  host: 127.0.0.1\n", encoding="utf-8")
    monkeypatch.setattr("agentgraph.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("agentgraph.config.CONFIG_FILE", config_file)
    monkeypatch.setattr("agentgraph.config.CONFIG_YAML_FILE", config_yaml_file)

    save_rss_config(
        RssConfig(
            feed_urls=["https://example.com/feed.xml"],
        )
    )

    assert load_rss_config() == {"feed_urls": ["https://example.com/feed.xml"]}
    rendered = config_yaml_file.read_text(encoding="utf-8")
    assert "connectors:" in rendered
    assert "rss:" in rendered
    assert "accounts:" not in rendered
    assert not config_file.exists()


def test_rss_config_prefers_yaml_over_toml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_file = tmp_path / "config.toml"
    config_yaml_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
[connectors.rss]
feed_urls = ["https://example.com/toml.xml"]
""",
        encoding="utf-8",
    )
    config_yaml_file.write_text(
        """
connectors:
  rss:
    feed_urls:
      - https://example.com/yaml.xml
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("agentgraph.config.CONFIG_FILE", config_file)
    monkeypatch.setattr("agentgraph.config.CONFIG_YAML_FILE", config_yaml_file)

    assert load_rss_config() == {"feed_urls": ["https://example.com/yaml.xml"]}


def test_add_feed_urls_creates_rss_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: dict[str, object] = {}

    monkeypatch.setattr(feedparser, "parse", lambda source: _ParsedFeed())
    monkeypatch.setattr(
        "agentgraph_connector_rss.auth.load_rss_settings",
        lambda account_id=None: (_ for _ in ()).throw(RuntimeError("missing")),
    )
    monkeypatch.setattr(
        "agentgraph_connector_rss.auth.save_rss_config",
        lambda data: saved.update({"data": data.model_dump(mode="json")}),
    )

    config = add_feed_urls(["https://example.com/feed.xml"])

    assert config.feed_urls == ["https://example.com/feed.xml"]
    assert saved["data"] == {
        "feed_urls": ["https://example.com/feed.xml"],
    }


def test_add_feed_urls_rejects_invalid_feed_before_saving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: dict[str, object] = {}

    monkeypatch.setattr(feedparser, "parse", lambda source: _ParsedNonFeed())
    monkeypatch.setattr(
        "agentgraph_connector_rss.auth.load_rss_settings",
        lambda account_id=None: (_ for _ in ()).throw(RuntimeError("missing")),
    )
    monkeypatch.setattr(
        "agentgraph_connector_rss.auth.save_rss_config",
        lambda data: saved.update({"data": data.model_dump(mode="json")}),
    )

    with pytest.raises(ValueError, match="Not a valid RSS/Atom feed"):
        add_feed_urls(["https://example.com/not-a-feed"])

    assert saved == {}


def test_remove_feed_urls_updates_existing_rss_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: dict[str, object] = {}

    monkeypatch.setattr(
        "agentgraph_connector_rss.auth.load_rss_settings",
        lambda account_id=None: RssConfig(
            feed_urls=[
                "https://example.com/one.xml",
                "https://example.com/two.xml",
            ],
        ),
    )
    monkeypatch.setattr(
        "agentgraph_connector_rss.auth.save_rss_config",
        lambda data: saved.update({"data": data.model_dump(mode="json")}),
    )

    config, removed = remove_feed_urls(["https://example.com/two.xml"])

    assert removed == ["https://example.com/two.xml"]
    assert config.feed_urls == ["https://example.com/one.xml"]
    assert saved == {
        "data": {
            "feed_urls": ["https://example.com/one.xml"],
        },
    }


def test_remove_feed_urls_rejects_unconfigured_feed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agentgraph_connector_rss.auth.load_rss_settings",
        lambda account_id=None: RssConfig(
            feed_urls=["https://example.com/one.xml"],
        ),
    )

    with pytest.raises(ValueError, match="No matching RSS feed URLs"):
        remove_feed_urls(["https://example.com/missing.xml"])


def test_resolve_feed_source_discovers_feed_from_html_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html_path = tmp_path / "index.html"
    html_path.write_text(
        """<!doctype html>
<html>
  <head>
    <link rel="alternate" type="application/rss+xml" href="https://example.com/feed.xml">
  </head>
</html>
""",
        encoding="utf-8",
    )

    def fake_parse(source: str) -> object:
        if source == "https://example.com/feed.xml":
            return _ParsedFeed()
        return _ParsedNonFeed()

    monkeypatch.setattr(feedparser, "parse", fake_parse)

    assert resolve_feed_source(str(html_path)) == "https://example.com/feed.xml"


def test_rss_connector_add_html_file_reports_discovered_feed_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html_path = tmp_path / "index.html"
    html_path.write_text(
        """<html><head>
<link rel="alternate" type="application/atom+xml" href="https://example.com/atom.xml">
</head></html>""",
        encoding="utf-8",
    )
    saved: dict[str, object] = {}

    def fake_parse(source: str) -> object:
        if source == "https://example.com/atom.xml":
            return _ParsedFeed()
        return _ParsedNonFeed()

    monkeypatch.setattr(feedparser, "parse", fake_parse)
    monkeypatch.setattr(
        "agentgraph_connector_rss.auth.load_rss_settings",
        lambda account_id=None: (_ for _ in ()).throw(RuntimeError("missing")),
    )
    monkeypatch.setattr(
        "agentgraph_connector_rss.auth.save_rss_config",
        lambda data: saved.update({"data": data.model_dump(mode="json")}),
    )

    result = RssConnector.run_cli_command(["add", str(html_path)])

    assert result["added"] == ["https://example.com/atom.xml"]
    assert saved["data"] == {
        "feed_urls": ["https://example.com/atom.xml"],
    }


def test_rss_connector_remove_reports_removed_feed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: dict[str, object] = {}

    monkeypatch.setattr(
        "agentgraph_connector_rss.auth.load_rss_settings",
        lambda account_id=None: RssConfig(
            feed_urls=[
                "https://example.com/one.xml",
                "https://example.com/two.xml",
            ],
        ),
    )
    monkeypatch.setattr(
        "agentgraph_connector_rss.auth.save_rss_config",
        lambda data: saved.update({"data": data.model_dump(mode="json")}),
    )

    result = RssConnector.run_cli_command(["remove", "https://example.com/two.xml"])

    assert result["removed"] == ["https://example.com/two.xml"]
    assert result["feed_urls"] == ["https://example.com/one.xml"]
    assert saved["data"] == {"feed_urls": ["https://example.com/one.xml"]}


def test_parse_opml_feeds_deduplicates_feed_urls(tmp_path: Path) -> None:
    opml_path = tmp_path / "feeds.opml"
    opml_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <body>
    <outline text="Tech">
      <outline text="Example One" title="Example One" type="rss" xmlUrl="https://example.com/feed.xml" htmlUrl="https://example.com/" />
      <outline text="Example Two" type="rss" xmlUrl="https://example.com/two.xml" />
      <outline text="Duplicate" type="rss" xmlUrl="https://example.com/feed.xml" />
    </outline>
  </body>
</opml>
""",
        encoding="utf-8",
    )

    feeds = parse_opml_feeds(opml_path)

    assert [feed.title for feed in feeds] == ["Example One", "Example Two"]
    assert [feed.feed_url for feed in feeds] == [
        "https://example.com/feed.xml",
        "https://example.com/two.xml",
    ]
    assert feeds[0].html_url == "https://example.com/"


def test_parse_opml_feeds_accepts_file_uri(tmp_path: Path) -> None:
    opml_path = tmp_path / "feeds with spaces.opml"
    opml_path.write_text(
        """<opml version="2.0"><body>
  <outline text="Example" xmlUrl="https://example.com/feed.xml" />
</body></opml>""",
        encoding="utf-8",
    )

    feeds = parse_opml_feeds(opml_path.as_uri())

    assert [feed.feed_url for feed in feeds] == ["https://example.com/feed.xml"]


def test_select_opml_feeds_supports_indexes_and_ranges(tmp_path: Path) -> None:
    opml_path = tmp_path / "feeds.opml"
    opml_path.write_text(
        """<opml version="2.0"><body>
  <outline text="One" xmlUrl="https://example.com/one.xml" />
  <outline text="Two" xmlUrl="https://example.com/two.xml" />
  <outline text="Three" xmlUrl="https://example.com/three.xml" />
</body></opml>""",
        encoding="utf-8",
    )
    feeds = parse_opml_feeds(opml_path)

    selected = select_opml_feeds(feeds, selection="1,3")
    ranged = select_opml_feeds(feeds, selection="2-3")

    assert [feed.feed_url for feed in selected] == [
        "https://example.com/one.xml",
        "https://example.com/three.xml",
    ]
    assert [feed.feed_url for feed in ranged] == [
        "https://example.com/two.xml",
        "https://example.com/three.xml",
    ]


def test_checkbox_select_opml_feeds_uses_questionary(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeChoice:
        def __init__(self, *, title: str, value: str, checked: bool) -> None:
            self.title = title
            self.value = value
            self.checked = checked

    class _FakeQuestion:
        def ask(self) -> list[str]:
            return ["https://example.com/two.xml"]

    def fake_checkbox(prompt: str, *, choices: list[_FakeChoice]) -> _FakeQuestion:
        assert "2 found" in prompt
        assert [choice.checked for choice in choices] == [False, True]
        return _FakeQuestion()

    questionary = ModuleType("questionary")
    questionary.__dict__["Choice"] = _FakeChoice
    questionary.__dict__["checkbox"] = fake_checkbox
    monkeypatch.setitem(sys.modules, "questionary", questionary)

    selected = _checkbox_select_opml_feeds(
        [
            OpmlFeed(title="One", feed_url="https://example.com/one.xml"),
            OpmlFeed(title="Two", feed_url="https://example.com/two.xml"),
        ],
        configured_feed_urls=["https://example.com/two.xml"],
    )

    assert selected == [OpmlFeed(title="Two", feed_url="https://example.com/two.xml")]


def test_import_opml_prompt_uses_existing_rss_feed_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opml_path = tmp_path / "feeds.opml"
    opml_path.write_text(
        """<opml version="2.0"><body>
  <outline text="One" xmlUrl="https://example.com/one.xml" />
  <outline text="Two" xmlUrl="https://example.com/two.xml" />
</body></opml>""",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(feedparser, "parse", lambda source: _ParsedFeed())

    def fake_select(
        feeds: list[OpmlFeed],
        *,
        include_all: bool = False,
        selection: str | None = None,
        configured_feed_urls: list[str] | None = None,
    ) -> list[OpmlFeed]:
        captured["configured_feed_urls"] = configured_feed_urls
        return [feeds[0]]

    monkeypatch.setattr(
        "agentgraph_connector_rss.auth.load_rss_settings",
        lambda account_id=None: RssConfig(
            feed_urls=["https://example.com/two.xml"],
        ),
    )
    monkeypatch.setattr("agentgraph_connector_rss.auth.select_opml_feeds", fake_select)
    monkeypatch.setattr(
        "agentgraph_connector_rss.auth.save_rss_config",
        lambda data: None,
    )

    import_opml_feeds(opml_path)

    assert captured["configured_feed_urls"] == ["https://example.com/two.xml"]


def test_rss_connector_import_opml_all(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opml_path = tmp_path / "feeds.opml"
    opml_path.write_text(
        """<opml version="2.0"><body>
  <outline text="One" xmlUrl="https://example.com/one.xml" />
  <outline text="Two" xmlUrl="https://example.com/two.xml" />
</body></opml>""",
        encoding="utf-8",
    )
    saved: dict[str, object] = {}

    monkeypatch.setattr(feedparser, "parse", lambda source: _ParsedFeed())
    monkeypatch.setattr(
        "agentgraph_connector_rss.auth.load_rss_settings",
        lambda account_id=None: (_ for _ in ()).throw(RuntimeError("missing")),
    )
    monkeypatch.setattr(
        "agentgraph_connector_rss.auth.save_rss_config",
        lambda data: saved.update({"data": data.model_dump(mode="json")}),
    )

    result = RssConnector.run_cli_command(["import-opml", str(opml_path), "--all"])

    assert result["status"] == "ok"
    assert result["imported_feed_count"] == 2
    assert result["selected_feed_count"] == 2
    assert result["added"] == [
        "https://example.com/one.xml",
        "https://example.com/two.xml",
    ]
    assert saved["data"] == {
        "feed_urls": ["https://example.com/one.xml", "https://example.com/two.xml"],
    }


def test_rss_connector_import_opml_select(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opml_path = tmp_path / "feeds.opml"
    opml_path.write_text(
        """<opml version="2.0"><body>
  <outline text="One" xmlUrl="https://example.com/one.xml" />
  <outline text="Two" xmlUrl="https://example.com/two.xml" />
</body></opml>""",
        encoding="utf-8",
    )
    saved: dict[str, object] = {}

    monkeypatch.setattr(feedparser, "parse", lambda source: _ParsedFeed())
    monkeypatch.setattr(
        "agentgraph_connector_rss.auth.load_rss_settings",
        lambda account_id=None: (_ for _ in ()).throw(RuntimeError("missing")),
    )
    monkeypatch.setattr(
        "agentgraph_connector_rss.auth.save_rss_config",
        lambda data: saved.update({"data": data.model_dump(mode="json")}),
    )

    result = RssConnector.run_cli_command(["import-opml", str(opml_path), "--select", "2"])

    assert result["selected_feed_count"] == 1
    assert result["added"] == ["https://example.com/two.xml"]
    assert saved["data"] == {
        "feed_urls": ["https://example.com/two.xml"],
    }


@pytest.mark.asyncio
async def test_verify_rss_auth_missing() -> None:
    with patch("agentgraph_connector_rss.auth.load_rss_settings", side_effect=RuntimeError("missing")):
        assert await verify_rss_auth() == ("missing", None)


@pytest.mark.asyncio
async def test_verify_rss_auth_requires_feed_urls() -> None:
    with patch(
        "agentgraph_connector_rss.auth.load_rss_settings",
        return_value=RssConfig(feed_urls=[]),
    ):
        assert await verify_rss_auth() == ("invalid", "No RSS feed URLs configured")


@pytest.mark.asyncio
async def test_verify_rss_auth_uses_feed_preview() -> None:
    with (
        patch(
            "agentgraph_connector_rss.auth.load_rss_settings",
            return_value=RssConfig(feed_urls=["https://example.com/feed.xml"]),
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
    assert feed.metadata["web_url"] == "https://example.com/feed.xml"
    assert entry.entity_type == "Document"
    assert entry.platform == "rss"
    assert entry.title == "First Post"
    assert entry.content and "A short summary" in entry.content
    assert entry.metadata["link"] == "https://example.com/first"
    assert entry.metadata["web_url"] == "https://example.com/first"
    assert batch.edges[0].edge_type == "posted_in"


@pytest.mark.asyncio
async def test_fetch_feed_hydrates_entry_documents_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            }
        ]

    monkeypatch.setattr(feedparser, "parse", lambda _feed_url: _Parsed())
    backend = MagicMock()
    backend.get_entity_by_platform = AsyncMock(return_value=None)
    set_backend(backend)

    fetched = EntityRecord(
        entity_type="Document",
        platform="web",
        platform_entity_id="https://example.com/first",
        title="Full First Post",
        content="Full article body",
        metadata={
            "web_url": "https://example.com/first",
            "http_etag": '"fresh"',
            "status_code": 200,
        },
    )

    with patch(
        "agentgraph_connector_rss._fetch_http_document", new=AsyncMock(return_value=fetched)
    ) as fetch:
        batch = await _fetch_feed("https://example.com/feed.xml", hydrate_documents=True)

    fetch.assert_awaited_once()
    assert fetch.await_args.args == ("https://example.com/first",)
    assert fetch.await_args.kwargs["existing_entity"] is None
    entry = batch.entities[1]
    assert entry.platform == "rss"
    assert entry.title == "Full First Post"
    assert entry.content == "Full article body"
    assert entry.created_at is not None
    assert entry.metadata["feed_url"] == "https://example.com/feed.xml"
    assert entry.metadata["web_url"] == "https://example.com/first"
    assert entry.metadata["http_etag"] == '"fresh"'


@pytest.mark.asyncio
async def test_fetch_feed_hydrates_existing_entries_with_cache_validators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Parsed:
        bozo = False
        feed = {"title": "Example Feed"}
        entries = [
            {
                "id": "post-1",
                "title": "First Post",
                "link": "https://example.com/first",
                "summary": "A short summary",
            }
        ]

    monkeypatch.setattr(feedparser, "parse", lambda _feed_url: _Parsed())
    existing = {
        "entity_type": "Document",
        "platform": "rss",
        "platform_entity_id": "entry/cached",
        "title": "Cached title",
        "content": "Cached body",
        "metadata": {
            "web_url": "https://example.com/first",
            "http_etag": '"cached"',
            "http_last_modified": "Sun, 07 Jun 2026 12:00:00 GMT",
        },
    }
    backend = MagicMock()
    backend.get_entity_by_platform = AsyncMock(return_value=existing)
    set_backend(backend)

    fetched = EntityRecord(
        entity_type="Document",
        platform="web",
        platform_entity_id="https://example.com/first",
        title="Cached title",
        content="Cached body",
        metadata={
            "web_url": "https://example.com/first",
            "http_etag": '"cached"',
            "http_last_modified": "Sun, 07 Jun 2026 12:00:00 GMT",
            "status_code": 304,
        },
    )

    with patch(
        "agentgraph_connector_rss._fetch_http_document", new=AsyncMock(return_value=fetched)
    ) as fetch:
        batch = await _fetch_feed("https://example.com/feed.xml", hydrate_documents=True)

    fetch.assert_awaited_once()
    existing_arg = fetch.await_args.kwargs["existing_entity"]
    assert existing_arg["platform_entity_id"] == "https://example.com/first"
    assert existing_arg["metadata"]["http_etag"] == '"cached"'
    entry = batch.entities[1]
    assert entry.content == "Cached body"
    assert entry.metadata["status_code"] == 304
    assert entry.metadata["http_etag"] == '"cached"'


@pytest.mark.asyncio
async def test_fetch_feed_keeps_entry_when_hydration_fails_without_error_log(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _Parsed:
        bozo = False
        feed = {"title": "Example Feed"}
        entries = [
            {
                "id": "post-1",
                "title": "First Post",
                "link": "https://missing.example/first",
                "summary": "A short summary",
            }
        ]

    monkeypatch.setattr(feedparser, "parse", lambda _feed_url: _Parsed())
    backend = MagicMock()
    backend.get_entity_by_platform = AsyncMock(return_value=None)
    set_backend(backend)
    caplog.set_level(logging.WARNING, logger="agentgraph_connector_rss")

    with patch(
        "agentgraph_connector_rss._fetch_http_document",
        new=AsyncMock(side_effect=RuntimeError("DNS lookup failed")),
    ):
        batch = await _fetch_feed("https://example.com/feed.xml", hydrate_documents=True)

    entry = batch.entities[1]
    assert entry.platform == "rss"
    assert entry.title == "First Post"
    assert entry.content and "A short summary" in entry.content
    assert entry.metadata["web_url"] == "https://missing.example/first"
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert "Skipping RSS article hydration for" in caplog.text
    assert "RuntimeError: DNS lookup failed" in caplog.text


@pytest.mark.asyncio
async def test_rss_fetch_entry_document_uses_http_document_cache() -> None:
    existing = {
        "entity_type": "Document",
        "platform": "rss",
        "platform_entity_id": "entry/cached",
        "title": "Cached",
        "content": "Cached content",
        "metadata": {
            "feed_url": "https://example.com/feed.xml",
            "feed_entity_id": "feed/abc",
            "link": "https://example.com/post",
            "web_url": "https://example.com/post",
            "http_etag": '"cached"',
        },
    }
    backend = MagicMock()
    backend.get_entity_by_platform = AsyncMock(return_value=existing)
    set_backend(backend)

    fetched = EntityRecord(
        entity_type="Document",
        platform="web",
        platform_entity_id="https://example.com/post",
        title="Fresh article",
        content="Fresh article body",
        metadata={
            "web_url": "https://example.com/post",
            "http_etag": '"fresh"',
            "http_last_modified": "Mon, 08 Jun 2026 01:23:45 GMT",
            "status_code": 200,
        },
    )

    with patch(
        "agentgraph_connector_rss._fetch_http_document", new=AsyncMock(return_value=fetched)
    ) as fetch:
        batch = await RssConnector().fetch(
            "document",
            "entry/cached",
            meta={
                "feed_url": "https://example.com/feed.xml",
                "feed_entity_id": "feed/abc",
                "link": "https://example.com/post",
                "web_url": "https://example.com/post",
                "http_etag": '"cached"',
            },
        )

    fetch.assert_awaited_once()
    existing_arg = fetch.await_args.kwargs["existing_entity"]
    assert existing_arg["platform_entity_id"] == "https://example.com/post"
    entity = batch.entities[0]
    assert entity.platform == "rss"
    assert entity.platform_entity_id == "entry/cached"
    assert entity.title == "Fresh article"
    assert entity.content == "Fresh article body"
    assert entity.metadata["feed_url"] == "https://example.com/feed.xml"
    assert entity.metadata["web_url"] == "https://example.com/post"
    assert entity.metadata["http_etag"] == '"fresh"'
