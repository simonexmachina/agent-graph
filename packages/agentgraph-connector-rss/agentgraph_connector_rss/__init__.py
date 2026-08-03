"""RSS and Atom connector."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from importlib import import_module
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from agentgraph.connectors.base import (
    BaseConnector,
    ConnectorAccount,
    EdgeRecord,
    EntityBatch,
    EntityRecord,
    FetchPolicy,
    ResourceType,
    SourceReference,
)
from agentgraph.core.context import get_backend
from agentgraph_connector_rss.auth import (
    add_feed_urls,
    import_opml_feeds,
    load_rss_settings,
    preview_feed,
    remove_feed_urls,
    resolve_feed_sources,
    run_rss_flow,
    verify_rss_auth,
)

_STALE_AFTER = 30 * 60
_FEED_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_MAX_FEED_BYTES = 5_000_000
_MAX_OBSERVATION_ENTRIES_PER_FEED = 64
_MAX_OBSERVATION_PATTERNS_PER_FEED = 5
_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "_hsenc",
    "_hsmi",
}
logger = logging.getLogger(__name__)


class RssConnector(BaseConnector):
    source = "rss"
    fetch_policy = FetchPolicy(stale_after_seconds=_STALE_AFTER)
    poll_interval: timedelta | None = timedelta(minutes=15)  # type: ignore[assignment]
    url_patterns = []
    auth_label = "rss"
    auth_description = "RSS/Atom feeds: feed URLs are fetched directly and entries are indexed as Document entities."
    onboard_prompt = "Set up RSS feeds?"
    appears_in_auth_status = False

    def __init__(self) -> None:
        self._observation_patterns: list[str] | None = None

    @classmethod
    def run_auth_flow(cls, account_id: str | None = None, add: bool = False) -> None:
        run_rss_flow(account_id=account_id, add=add)

    @classmethod
    def get_authenticated_user(cls) -> str | None:
        try:
            settings = load_rss_settings()
        except RuntimeError:
            return None
        return "RSS" if settings.feed_urls else None

    @classmethod
    def list_accounts(cls) -> list[ConnectorAccount]:
        return []

    @classmethod
    async def verify_auth(cls, account_id: str | None = None) -> tuple[str, str | None]:
        return await verify_rss_auth(account_id)

    @classmethod
    def run_cli_command(cls, args: list[str]) -> dict[str, Any]:
        if not args:
            raise ValueError(_rss_usage())
        command, *rest = args
        if command == "add":
            sources = _parse_feed_url_args(rest, command="add")
            feed_urls = resolve_feed_sources(sources)
            config = add_feed_urls(feed_urls, validate=False)
            return {
                "status": "ok",
                "source": cls.source,
                "feed_urls": config.feed_urls,
                "added": feed_urls,
            }
        if command == "remove":
            feed_urls = _parse_feed_url_args(rest, command="remove")
            config, removed_feed_urls = remove_feed_urls(feed_urls)
            return {
                "status": "ok",
                "source": cls.source,
                "feed_urls": config.feed_urls,
                "removed": removed_feed_urls,
            }
        if command == "import-opml":
            options = _parse_import_opml_args(rest)
            config, feeds, selected_feeds = import_opml_feeds(**options)
            selected_feed_urls = [feed.feed_url for feed in selected_feeds]
            return {
                "status": "ok",
                "source": cls.source,
                "feed_urls": config.feed_urls,
                "imported_feed_count": len(feeds),
                "selected_feed_count": len(selected_feeds),
                "added": selected_feed_urls,
            }
        raise ValueError(f"Unknown rss connector command '{command}'. Available: add, remove, import-opml")

    @classmethod
    def cli_help(cls) -> str:
        return _rss_help()

    @classmethod
    def format_cli_result(cls, result: dict[str, Any]) -> str:
        return _format_rss_cli_result(result)

    def can_handle(self, url: str) -> bool:
        return self.resolve_url(url) is not None

    def resolve_url(self, url: str) -> SourceReference | None:
        try:
            settings = load_rss_settings()
        except RuntimeError:
            return None
        if url not in settings.feed_urls:
            return None
        return SourceReference(
            source=self.source,
            resource_type="document",
            resource_id=url,
        )

    async def resolve_observation_url(self, url: str) -> SourceReference | None:
        configured_feed = self.resolve_url(url)
        if configured_feed is not None:
            return configured_feed

        normalised_url = normalise_article_url(url)
        if normalised_url is None:
            return None
        try:
            backend = get_backend()
        except RuntimeError:
            return None
        entries = await backend.query_by_filter(
            "Document",
            {"platform": self.source, "web_url": normalised_url},
            1,
            "updated_at",
            None,
            None,
        )
        if not entries:
            return None
        entry = entries[0]
        platform_entity_id = entry.get("platform_entity_id")
        metadata = entry.get("metadata")
        if not isinstance(platform_entity_id, str) or not isinstance(metadata, Mapping):
            return None
        return SourceReference(
            source=self.source,
            resource_type="document",
            resource_id=platform_entity_id,
            fetch_meta=_string_metadata(metadata),
        )

    async def observation_url_patterns(self) -> list[str]:
        if self._observation_patterns is not None:
            return self._observation_patterns
        try:
            settings = load_rss_settings()
        except RuntimeError:
            return []

        links_by_feed: dict[str, list[str]] = {}
        backend = get_backend()
        for feed_url in settings.feed_urls:
            entries = await backend.query_by_filter(
                "Document",
                {"platform": self.source, "feed_url": feed_url},
                _MAX_OBSERVATION_ENTRIES_PER_FEED,
                "updated_at",
                None,
                None,
            )
            links_by_feed[feed_url] = _entry_links(entries)
        self._observation_patterns = derive_observation_url_patterns(links_by_feed)
        return self._observation_patterns

    async def ingest(self, account_id: str | None = None) -> EntityBatch:
        settings = load_rss_settings(account_id)
        combined = EntityBatch()
        for feed_url in settings.feed_urls:
            try:
                batch = await _fetch_feed(feed_url, hydrate_documents=True)
            except Exception as exc:
                logger.warning(
                    "Skipping RSS feed %s (%s: %s)",
                    feed_url,
                    type(exc).__name__,
                    exc,
                )
                logger.debug("RSS feed fetch failure", exc_info=True)
                continue
            combined.entities.extend(batch.entities)
            combined.edges.extend(batch.edges)
            combined.persons.extend(batch.persons)
        self._observation_patterns = derive_observation_url_patterns(
            _entry_links_by_feed(combined.entities)
        )
        return combined

    async def poll(
        self,
        cursor: dict[str, Any],
        account_id: str | None = None,
    ) -> tuple[EntityBatch, dict[str, Any]]:
        _ = cursor
        batch = await self.ingest(account_id=account_id)
        return batch, {"last_polled_at": datetime.now(UTC).isoformat()}

    async def preview_feed(self, feed_url: str, *, count: int = 3) -> dict[str, Any]:
        return await preview_feed(feed_url, count=count)

    async def fetch(
        self,
        resource_type: ResourceType,
        resource_id: str,
        meta: dict[str, str] | None = None,
        account_id: str | None = None,
    ) -> EntityBatch:
        _ = (resource_type, meta, account_id)
        if resource_id.startswith(("http://", "https://")):
            return await _fetch_feed(resource_id)
        if resource_type == "document" and meta and meta.get("web_url"):
            entity = await _fetch_entry_document(resource_id, meta)
            return EntityBatch(entities=[entity])
        return EntityBatch()


async def _fetch_feed(feed_url: str, *, hydrate_documents: bool = False) -> EntityBatch:
    parsed = await _parse_feed(feed_url)
    feed_title = str(cast(dict[str, Any], parsed.feed).get("title") or feed_url)
    feed_id = _feed_id(feed_url)
    feed_entity_id = f"feed/{feed_id}"
    entities = [
        EntityRecord(
            entity_type="Folder",
            platform="rss",
            platform_entity_id=feed_entity_id,
            title=feed_title,
            content=f"RSS feed: {feed_title}\n{feed_url}",
            metadata={"feed_url": feed_url, "web_url": feed_url},
        )
    ]
    edges: list[EdgeRecord] = []
    batch = EntityBatch()

    for raw_entry in cast(list[Any], parsed.entries):
        entry = cast(dict[str, Any], raw_entry)
        entity = _entry_to_entity(feed_url, feed_entity_id, entry)
        if hydrate_documents:
            entity = await _hydrate_entry_document(entity)
        entities.append(entity)
        edges.append(
            EdgeRecord(
                edge_type="posted_in",
                source_platform_entity_id=entity.platform_entity_id,
                target_platform_entity_id=feed_entity_id,
                platform="rss",
            )
        )
        batch.add_stubs_from(entity)

    batch.entities = [*entities, *batch.entities]
    batch.edges = [*edges, *batch.edges]
    return batch


async def _parse_feed(feed_url: str) -> Any:
    import asyncio

    import feedparser  # type: ignore[import-untyped]

    async with httpx.AsyncClient(
        follow_redirects=True,
        max_redirects=5,
        timeout=_FEED_TIMEOUT,
        headers={"Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"},
    ) as client:
        response = await client.get(feed_url)
        response.raise_for_status()
        content = response.content
        if len(content) > _MAX_FEED_BYTES:
            raise ValueError(f"RSS feed response too large: limit is {_MAX_FEED_BYTES} bytes")
        return await asyncio.to_thread(feedparser.parse, content)


def _rss_usage() -> str:
    return (
        "Usage: agentgraph connector rss add <feed-or-html-url> [feed-or-html-url...]\n"
        "   or: agentgraph connector rss remove <feed-url> [feed-url...]\n"
        "   or: agentgraph connector rss import-opml <file.opml> [--all | --select <indexes>]"
    )


def _rss_help() -> str:
    return "\n".join(
        [
            "RSS connector commands:",
            "",
            _rss_usage(),
            "",
            "Commands:",
            "  add <feed-or-html-url> [feed-or-html-url...]",
            "      Add one or more RSS/Atom feeds. HTML pages are scanned for RSS/Atom <link> tags.",
            "  remove <feed-url> [feed-url...]",
            "      Remove one or more exact RSS/Atom feed URLs from the configured feed list.",
            "  import-opml <file.opml> [--all | --select <indexes>]",
            "      Import RSS/Atom feed URLs from an OPML file. Omit flags for checkbox selection.",
            "",
            "Options:",
            "  --all                   Import every feed from the OPML file.",
            "  --select <indexes>      Import selected feed numbers, e.g. 1,3-5.",
            "  --json                  Output command results as JSON.",
        ]
    )


def _format_rss_cli_result(result: dict[str, Any]) -> str:
    added = [str(item) for item in cast(list[object], result.get("added") or [])]
    removed = [str(item) for item in cast(list[object], result.get("removed") or [])]
    feed_urls = cast(list[object], result.get("feed_urls") or [])

    if "imported_feed_count" in result:
        imported_count = int(result.get("imported_feed_count") or 0)
        selected_count = int(result.get("selected_feed_count") or len(added))
        lines = [
            f"Imported {selected_count} of {imported_count} feed(s)."
        ]
    elif "removed" in result:
        lines = [f"Removed {len(removed)} feed(s)."]
    else:
        lines = [f"Added {len(added)} feed(s)."]

    if added:
        lines.append("Added feeds:")
        lines.extend(f"  - {feed_url}" for feed_url in added[:20])
        if len(added) > 20:
            lines.append(f"  ... {len(added) - 20} more")
    if removed:
        lines.append("Removed feeds:")
        lines.extend(f"  - {feed_url}" for feed_url in removed[:20])
        if len(removed) > 20:
            lines.append(f"  ... {len(removed) - 20} more")
    lines.append(f"Total configured feeds: {len(feed_urls)}")
    return "\n".join(lines)


def _parse_feed_url_args(args: list[str], *, command: str) -> list[str]:
    for arg in args:
        if arg.startswith("--"):
            raise ValueError(f"Unknown {command} option: {arg}")
    return args


def _parse_import_opml_args(args: list[str]) -> dict[str, Any]:
    path: str | None = None
    include_all = False
    selection: str | None = None
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--all":
            include_all = True
            index += 1
            continue
        if arg == "--select":
            if index + 1 >= len(args):
                raise ValueError("--select requires a value")
            selection = args[index + 1]
            index += 2
            continue
        if arg.startswith("--"):
            raise ValueError(f"Unknown import-opml option: {arg}")
        if path is not None:
            raise ValueError(_rss_usage())
        path = arg
        index += 1
    if path is None:
        raise ValueError(_rss_usage())
    if include_all and selection is not None:
        raise ValueError("Use either --all or --select, not both")
    return {
        "path": path,
        "include_all": include_all,
        "selection": selection,
    }


def _entry_to_entity(
    feed_url: str,
    feed_entity_id: str,
    entry: dict[str, Any],
) -> EntityRecord:
    link = normalise_article_url(str(entry.get("link") or "")) or ""
    external_id = str(entry.get("id") or entry.get("guid") or link or entry.get("title") or "")
    entity_id = f"entry/{_hash_ref(feed_url + ':' + external_id)}"
    title = str(entry.get("title") or link or "(untitled)")
    summary = _entry_text(entry)
    published = _parse_entry_datetime(entry.get("published") or entry.get("updated"))
    metadata: dict[str, str | int | float | bool | None] = {
        "feed_url": feed_url,
        "feed_entity_id": feed_entity_id,
        "link": link or None,
        "web_url": link or None,
        "author": str(entry.get("author")) if entry.get("author") else None,
    }
    content_parts = [title]
    if summary:
        content_parts.append(summary)
    if link:
        content_parts.append(link)
    return EntityRecord(
        entity_type="Document",
        platform="rss",
        platform_entity_id=entity_id,
        title=title,
        content="\n\n".join(content_parts),
        created_at=published,
        updated_at=_parse_entry_datetime(entry.get("updated")) or published,
        metadata=metadata,
    )


async def _fetch_entry_document(
    platform_entity_id: str,
    metadata: Mapping[str, object],
    *,
    fallback: EntityRecord | None = None,
) -> EntityRecord:
    web_url = _metadata_str(metadata, "web_url")
    if web_url is None:
        raise ValueError(f"RSS document {platform_entity_id} has no web_url")
    existing = await get_backend().get_entity_by_platform("rss", platform_entity_id)
    http_existing = _http_existing_entity(existing, web_url)
    fetched = await _fetch_http_document(web_url, existing_entity=http_existing)
    fetched_metadata = dict(fetched.metadata)
    rss_metadata: dict[str, str | int | float | bool | None] = {
        **_entity_record_metadata(metadata),
        **fetched_metadata,
        "web_url": str(fetched_metadata.get("web_url") or web_url),
        "link": _metadata_str(metadata, "link") or web_url,
    }
    return EntityRecord(
        entity_type="Document",
        platform="rss",
        platform_entity_id=platform_entity_id,
        title=fetched.title or (fallback.title if fallback else None),
        content=fetched.content or (fallback.content if fallback else None),
        created_at=fallback.created_at if fallback else None,
        updated_at=fetched.updated_at or (fallback.updated_at if fallback else None),
        metadata=rss_metadata,
    )


async def _hydrate_entry_document(entity: EntityRecord) -> EntityRecord:
    if _metadata_str(entity.metadata, "web_url") is None:
        return entity
    try:
        return await _fetch_entry_document(
            entity.platform_entity_id,
            entity.metadata,
            fallback=entity,
        )
    except Exception as exc:
        logger.warning(
            "Skipping RSS article hydration for %s (%s: %s)",
            entity.platform_entity_id,
            type(exc).__name__,
            exc,
        )
        logger.debug("RSS article hydration failure", exc_info=True)
        return entity


def _http_existing_entity(
    existing: dict[str, Any] | None,
    web_url: str,
) -> dict[str, object] | None:
    if existing is None:
        return None
    http_existing = dict(existing)
    http_existing["platform_entity_id"] = web_url
    return http_existing


async def _fetch_http_document(
    url: str,
    *,
    existing_entity: dict[str, object] | None,
) -> EntityRecord:
    module: Any = import_module("agentgraph_connector_web")
    result = await module.fetch_http_document(url, existing_entity=existing_entity)
    return cast(EntityRecord, result)


def _entity_record_metadata(
    metadata: Mapping[str, object],
) -> dict[str, str | int | float | bool | None]:
    result: dict[str, str | int | float | bool | None] = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
    return result


def _metadata_str(metadata: Mapping[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def _string_metadata(metadata: Mapping[str, object]) -> dict[str, str]:
    return {key: value for key, value in metadata.items() if isinstance(value, str)}


def normalise_article_url(url: str) -> str | None:
    """Canonicalise an RSS entry URL for exact observation matching."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    query_items = sorted(
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not _is_tracking_query_key(key)
    )
    query = urlencode(query_items, doseq=True)
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


def derive_observation_url_patterns(links_by_feed: Mapping[str, list[str]]) -> list[str]:
    """Build bounded Chrome patterns from previously indexed article links."""
    patterns: list[str] = []
    seen: set[str] = set()
    for links in links_by_feed.values():
        candidates: dict[str, set[str]] = {}
        for raw_link in links:
            link = normalise_article_url(raw_link)
            if link is None:
                continue
            parsed = urlsplit(link)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            segments = [segment for segment in parsed.path.split("/") if segment]
            for depth in range(1, len(segments)):
                prefix = f"{origin}/{'/'.join(segments[:depth])}"
                candidates.setdefault(prefix, set()).add(link)
            candidates.setdefault(origin, set()).add(link)

        shared = [
            (prefix, urls)
            for prefix, urls in candidates.items()
            if len(urls) >= 2 and prefix.count("/") > 2
        ]
        useful = shared or [(prefix, urls) for prefix, urls in candidates.items() if len(urls) >= 1]
        useful.sort(
            key=lambda item: (
                -item[0].removeprefix("https://").removeprefix("http://").count("/"),
                -len(item[1]),
                item[0],
            )
        )
        for prefix, _urls in useful[:_MAX_OBSERVATION_PATTERNS_PER_FEED]:
            pattern = f"{prefix}/*"
            if pattern not in seen:
                patterns.append(pattern)
                seen.add(pattern)
    return patterns


def _is_tracking_query_key(key: str) -> bool:
    return key.lower().startswith("utm_") or key.lower() in _TRACKING_QUERY_KEYS


def _entry_links(entries: Sequence[Mapping[str, object]]) -> list[str]:
    links: list[str] = []
    for entry in entries:
        metadata = entry.get("metadata")
        if not isinstance(metadata, Mapping):
            continue
        link = _metadata_str(metadata, "web_url") or _metadata_str(metadata, "link")
        if link is not None:
            links.append(link)
    return links


def _entry_links_by_feed(entities: list[EntityRecord]) -> dict[str, list[str]]:
    links_by_feed: dict[str, list[str]] = {}
    for entity in entities:
        if entity.entity_type != "Document":
            continue
        feed_url = _metadata_str(entity.metadata, "feed_url")
        link = _metadata_str(entity.metadata, "web_url") or _metadata_str(entity.metadata, "link")
        if feed_url is not None and link is not None:
            links_by_feed.setdefault(feed_url, []).append(link)
    return links_by_feed


def _entry_text(entry: dict[str, Any]) -> str:
    content = entry.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and first.get("value"):
            return str(first["value"])
    return str(entry.get("summary") or entry.get("description") or "")


def _parse_entry_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except Exception:
        return None


def _feed_id(feed_url: str) -> str:
    return _hash_ref(feed_url)


def _hash_ref(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
