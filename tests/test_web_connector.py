"""Tests for the generic web connector."""

from __future__ import annotations

import agentgraph_connector_web
import httpx
import pytest
from agentgraph_connector_web import UnsupportedFormatError, WebConnector

from agentgraph.connectors.base import SourceReference


def test_web_connector_resolves_http_urls() -> None:
    connector = WebConnector()

    assert connector.resolve_url("https://example.com/page#section") == SourceReference(
        source="web",
        resource_type="document",
        resource_id="https://example.com/page",
    )
    assert connector.resolve_url("ftp://example.com/file") is None


def test_parse_html_extracts_title_and_preserves_source() -> None:
    source = (
        b"<html><head><title>Hello</title><script>x()</script></head>"
        b"<body><h1>Hi</h1><p>World</p></body></html>"
    )
    parsed = agentgraph_connector_web._parse_content(  # noqa: SLF001
        source,
        "text/html",
        "https://example.com/hello",
    )

    assert parsed.title == "Hello"
    assert parsed.content == source.decode()


def test_parse_markdown_uses_first_heading() -> None:
    parsed = agentgraph_connector_web._parse_content(  # noqa: SLF001
        b"# Notes\n\nBody",
        "text/markdown",
        "https://example.com/notes.md",
    )

    assert parsed.title == "Notes"
    assert parsed.content == "# Notes\n\nBody"


def test_parse_json_uses_title_key() -> None:
    source = b'{"title":"API","ok":true}'
    parsed = agentgraph_connector_web._parse_content(  # noqa: SLF001
        source,
        "application/json",
        "https://example.com/api",
    )

    assert parsed.title == "API"
    assert parsed.content == source.decode()


def test_parse_plain_text() -> None:
    parsed = agentgraph_connector_web._parse_content(  # noqa: SLF001
        b"plain notes",
        "text/plain",
        "https://example.com/plain.txt",
    )

    assert parsed.title == "plain.txt"
    assert parsed.content == "plain notes"


def test_parse_xml_uses_first_title() -> None:
    source = b"<rss><channel><title>Feed</title><item><title>Entry</title></item></channel></rss>"
    parsed = agentgraph_connector_web._parse_content(  # noqa: SLF001
        source,
        "application/rss+xml",
        "https://example.com/feed.xml",
    )

    assert parsed.title == "Feed"
    assert parsed.content == source.decode()


def test_parse_unsupported_content_type_raises_clear_error() -> None:
    with pytest.raises(UnsupportedFormatError, match="Unsupported content type"):
        agentgraph_connector_web._parse_content(  # noqa: SLF001
            b"%PDF",
            "application/pdf",
            "https://example.com/file.pdf",
        )


def test_conditional_request_headers_use_document_metadata() -> None:
    headers = agentgraph_connector_web._conditional_request_headers(  # noqa: SLF001
        {
            "http_etag": '"abc123"',
            "http_last_modified": "Mon, 08 Jun 2026 00:00:00 GMT",
        }
    )

    assert headers == {
        "If-None-Match": '"abc123"',
        "If-Modified-Since": "Mon, 08 Jun 2026 00:00:00 GMT",
    }


@pytest.mark.asyncio
async def test_fetch_web_entity_streams_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "text/html",
                "etag": '"fresh"',
                "last-modified": "Mon, 08 Jun 2026 01:23:45 GMT",
            },
            content=b"<title>Fetched</title><p>Body</p>",
            request=request,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    ) as client:
        entity = await agentgraph_connector_web._fetch_web_entity(  # noqa: SLF001
            "https://example.com/page",
            client=client,
        )

    assert entity.platform == "web"
    assert entity.platform_entity_id == "https://example.com/page"
    assert entity.title == "Fetched"
    assert entity.content == "<title>Fetched</title><p>Body</p>"
    assert entity.metadata["content_type"] == "text/html"
    assert entity.metadata["web_url"] == "https://example.com/page"
    assert entity.metadata["http_etag"] == '"fresh"'
    assert entity.metadata["http_last_modified"] == "Mon, 08 Jun 2026 01:23:45 GMT"


@pytest.mark.asyncio
async def test_fetch_web_entity_uses_document_validators_on_304() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["if-none-match"] == '"cached"'
        assert request.headers["if-modified-since"] == "Sun, 07 Jun 2026 12:00:00 GMT"
        return httpx.Response(
            304,
            headers={
                "etag": '"cached"',
                "last-modified": "Sun, 07 Jun 2026 12:00:00 GMT",
            },
            request=request,
        )

    existing = {
        "entity_type": "Document",
        "platform": "web",
        "platform_entity_id": "https://example.com/page",
        "title": "Cached title",
        "content": "Cached body",
        "metadata": {
            "web_url": "https://example.com/page",
            "content_sha256": "cached-hash",
            "http_etag": '"cached"',
            "http_last_modified": "Sun, 07 Jun 2026 12:00:00 GMT",
        },
    }

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        entity = await agentgraph_connector_web._fetch_web_entity(  # noqa: SLF001
            "https://example.com/page",
            client=client,
            existing_entity=existing,
        )

    assert entity.title == "Cached title"
    assert entity.content == "Cached body"
    assert entity.metadata["status_code"] == 304
    assert entity.metadata["content_sha256"] == "cached-hash"
    assert entity.metadata["http_etag"] == '"cached"'


@pytest.mark.asyncio
async def test_fetch_web_entity_caps_response_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agentgraph_connector_web, "_MAX_BYTES", 5)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"too much text",
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="Response too large"):
            await agentgraph_connector_web._fetch_web_entity(  # noqa: SLF001
                "https://example.com/large",
                client=client,
            )
