"""Generic web connector."""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import ClassVar, cast
from urllib.parse import urldefrag, urlparse
from xml.etree import ElementTree

import httpx

from agentgraph.connectors.base import (
    BaseConnector,
    EntityBatch,
    EntityRecord,
    FetchPolicy,
    ResourceType,
    SourceReference,
)
from agentgraph.core.context import get_backend
from agentgraph.graph.upsert import upsert_batch

_STALE_AFTER = 24 * 60 * 60
_MAX_BYTES = 2_000_000
_MAX_REDIRECTS = 5
_ACCEPT = (
    "text/markdown, text/html, application/json, text/plain, "
    "application/atom+xml, application/rss+xml, application/xml, text/xml, "
    "application/pdf;q=0.7, */*;q=0.1"
)


class UnsupportedFormatError(ValueError):
    """Raised when a URL returns content AgentGraph cannot store for LLM use."""


class WebConnector(BaseConnector):
    source = "web"
    fetch_policy = FetchPolicy(stale_after_seconds=_STALE_AFTER)
    is_generic_url_fallback = True
    url_patterns: ClassVar[list[str]] = []
    auth_description = "Generic web pages: HTML, Markdown, JSON, plain text, and XML/RSS/Atom documents fetched directly over HTTP."
    appears_in_auth_status = False

    def can_handle(self, url: str) -> bool:
        return self.resolve_url(url) is not None

    def resolve_url(self, url: str) -> SourceReference | None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        return SourceReference(
            source=self.source,
            resource_type="document",
            resource_id=_canonical_url(url),
        )

    async def fetch(
        self,
        resource_type: ResourceType,
        resource_id: str,
        meta: dict[str, str] | None = None,
        account_id: str | None = None,
    ) -> EntityBatch:
        _ = (resource_type, meta, account_id)
        ref = self.resolve_url(resource_id)
        if ref is None:
            raise ValueError("Web connector only supports http:// and https:// URLs")

        existing = await get_backend().get_entity_by_platform(self.source, ref.resource_id)
        entity = await _fetch_web_entity(ref.resource_id, existing_entity=existing)
        batch = EntityBatch(entities=[entity])
        await upsert_batch(batch)
        return batch

    def entity_url(self, platform_entity_id: str) -> str | None:
        return platform_entity_id


async def _fetch_web_entity(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    existing_entity: dict[str, object] | None = None,
) -> EntityRecord:
    if client is None:
        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=_MAX_REDIRECTS,
            timeout=httpx.Timeout(10.0, connect=5.0),
        ) as owned_client:
            return await _fetch_web_entity(
                url,
                client=owned_client,
                existing_entity=existing_entity,
            )

    existing_metadata = _entity_metadata(existing_entity)
    headers = {
        "Accept": _ACCEPT,
        "User-Agent": "AgentGraph/0.1",
        **_conditional_request_headers(existing_metadata),
    }
    async with client.stream("GET", url, headers=headers) as response:
        if response.status_code == 304:
            if existing_entity is None:
                raise ValueError(f"Received 304 for {url} without an existing Document")
            return _not_modified_entity(url, response, existing_entity)

        response.raise_for_status()
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > _MAX_BYTES:
                raise ValueError(f"Response too large for web bookmark: limit is {_MAX_BYTES} bytes")

        content_type = _normalise_content_type(response.headers.get("content-type", ""))
        final_url = _canonical_url(str(response.url))
        parsed = _parse_content(bytes(body), content_type, final_url)
        return EntityRecord(
            entity_type="Document",
            platform="web",
            platform_entity_id=final_url,
            title=parsed.title,
            content=parsed.content,
            updated_at=datetime.now(UTC),
            metadata={
                "url": url,
                "final_url": final_url,
                "web_url": final_url,
                "content_type": content_type,
                "status_code": response.status_code,
                "fetched_at": datetime.now(UTC).isoformat(),
                "content_sha256": hashlib.sha256(body).hexdigest(),
                **_response_cache_metadata(response.headers),
            },
        )


async def fetch_http_document(
    url: str,
    *,
    existing_entity: dict[str, object] | None = None,
) -> EntityRecord:
    """Fetch an HTTP-backed Document, using validators from existing metadata when present."""
    return await _fetch_web_entity(url, existing_entity=existing_entity)


def _conditional_request_headers(metadata: dict[str, object]) -> dict[str, str]:
    headers: dict[str, str] = {}
    etag = metadata.get("http_etag")
    if isinstance(etag, str) and etag:
        headers["If-None-Match"] = etag
    last_modified = metadata.get("http_last_modified")
    if isinstance(last_modified, str) and last_modified:
        headers["If-Modified-Since"] = last_modified
    return headers


def _response_cache_metadata(headers: httpx.Headers) -> dict[str, str]:
    metadata: dict[str, str] = {}
    etag = headers.get("etag")
    if etag:
        metadata["http_etag"] = etag
    last_modified = headers.get("last-modified")
    if last_modified:
        metadata["http_last_modified"] = last_modified
    return metadata


def _entity_metadata(entity: dict[str, object] | None) -> dict[str, object]:
    metadata = entity.get("metadata") if entity is not None else None
    return cast(dict[str, object], metadata) if isinstance(metadata, dict) else {}


def _not_modified_entity(
    url: str,
    response: httpx.Response,
    existing_entity: dict[str, object],
) -> EntityRecord:
    metadata: dict[str, str | int | float | bool | None] = {
        **_entity_record_metadata(existing_entity),
        "url": url,
        "final_url": str(existing_entity.get("platform_entity_id") or url),
        "web_url": str(existing_entity.get("platform_entity_id") or url),
        "status_code": response.status_code,
        "fetched_at": datetime.now(UTC).isoformat(),
        **_response_cache_metadata(response.headers),
    }
    return EntityRecord(
        entity_type=str(existing_entity.get("entity_type") or "Document"),
        platform="web",
        platform_entity_id=str(existing_entity.get("platform_entity_id") or url),
        title=_optional_str(existing_entity.get("title")),
        content=_optional_str(existing_entity.get("content")),
        updated_at=datetime.now(UTC),
        metadata=metadata,
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _entity_record_metadata(
    entity: dict[str, object],
) -> dict[str, str | int | float | bool | None]:
    metadata: dict[str, str | int | float | bool | None] = {}
    for key, value in _entity_metadata(entity).items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            metadata[key] = value
    return metadata


class _ParsedContent:
    def __init__(self, *, title: str, content: str) -> None:
        self.title = title
        self.content = content


def _parse_content(body: bytes, content_type: str, url: str) -> _ParsedContent:
    text = _decode_text(body)
    if _is_html(content_type):
        return _parse_html(text, url)
    if _is_markdown(content_type, url):
        return _parse_markdown(text, url)
    if _is_json(content_type):
        return _parse_json(text, url)
    if _is_plain_text(content_type):
        return _ParsedContent(title=_title_from_url(url), content=text.strip())
    if _is_xml(content_type):
        return _parse_xml(text, url)
    raise UnsupportedFormatError(
        f"Unsupported content type for web bookmark: {content_type or 'unknown'}"
    )


def _decode_text(body: bytes) -> str:
    return body.decode("utf-8", errors="replace")


def _normalise_content_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def _is_html(content_type: str) -> bool:
    return content_type in {"text/html", "application/xhtml+xml"}


def _is_markdown(content_type: str, url: str) -> bool:
    return content_type in {"text/markdown", "text/x-markdown"} or urlparse(url).path.endswith(
        (".md", ".markdown")
    )


def _is_json(content_type: str) -> bool:
    return content_type == "application/json" or content_type.endswith("+json")


def _is_plain_text(content_type: str) -> bool:
    return content_type == "text/plain"


def _is_xml(content_type: str) -> bool:
    return content_type in {
        "application/atom+xml",
        "application/rss+xml",
        "application/xml",
        "text/xml",
    } or content_type.endswith("+xml")


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._tag_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        _ = attrs
        self._tag_stack.append(tag)
        if tag in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()
        elif tag in self._tag_stack:
            self._tag_stack.remove(tag)
        if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if any(tag in {"script", "style", "noscript"} for tag in self._tag_stack):
            return
        if self._tag_stack and self._tag_stack[-1] == "title":
            self.title_parts.append(data)
            return
        self.text_parts.append(data)


def _parse_html(text: str, url: str) -> _ParsedContent:
    parser = _TextHTMLParser()
    parser.feed(text)
    title = _clean_text(" ".join(parser.title_parts)) or _title_from_url(url)
    return _ParsedContent(title=title, content=text.strip())


def _parse_markdown(text: str, url: str) -> _ParsedContent:
    stripped = text.strip()
    title = _title_from_url(url)
    for line in stripped.splitlines():
        match = re.match(r"^#\s+(.+)$", line.strip())
        if match:
            title = match.group(1).strip()
            break
    return _ParsedContent(title=title, content=stripped)


def _parse_json(text: str, url: str) -> _ParsedContent:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON response for web bookmark: {exc.msg}") from exc
    title = _json_title(value) or _title_from_url(url)
    return _ParsedContent(title=title, content=text.strip())


def _json_title(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    items = cast(dict[str, object], value)
    for key in ("title", "name", "headline"):
        item = items.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    return None


def _parse_xml(text: str, url: str) -> _ParsedContent:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise ValueError(f"Invalid XML response for web bookmark: {exc}") from exc
    title = _xml_title(root) or _title_from_url(url)
    return _ParsedContent(title=title, content=text.strip())


def _xml_title(root: ElementTree.Element) -> str | None:
    for element in root.iter():
        if _strip_namespace(element.tag).lower() == "title":
            title = _clean_text(element.text or "")
            if title:
                return title
    return None


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _title_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path:
        return parsed.netloc
    return html.unescape(path.rsplit("/", 1)[-1]) or parsed.netloc


def _canonical_url(url: str) -> str:
    return urldefrag(url)[0]


def _clean_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
