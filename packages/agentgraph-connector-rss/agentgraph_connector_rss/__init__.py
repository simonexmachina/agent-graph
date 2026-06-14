"""RSS and Atom connector."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from importlib import import_module
from typing import Any, cast

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
logger = logging.getLogger(__name__)


class RssConnector(BaseConnector):
    source = "rss"
    fetch_policy = FetchPolicy(stale_after_seconds=_STALE_AFTER)
    poll_interval: timedelta | None = timedelta(minutes=15)  # type: ignore[assignment]
    url_patterns = []
    auth_label = "rss"
    auth_description = "RSS/Atom feeds: feed URLs are fetched directly and entries are indexed as Document entities."
    onboard_prompt = "Set up RSS feeds?"

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

    async def ingest(self, account_id: str | None = None) -> EntityBatch:
        settings = load_rss_settings(account_id)
        combined = EntityBatch()
        for feed_url in settings.feed_urls:
            batch = await _fetch_feed(feed_url, hydrate_documents=True)
            combined.entities.extend(batch.entities)
            combined.edges.extend(batch.edges)
            combined.persons.extend(batch.persons)
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
    import asyncio

    import feedparser  # type: ignore[import-untyped]

    parsed: Any = await asyncio.to_thread(feedparser.parse, feed_url)
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
    link = str(entry.get("link") or "")
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
    except Exception:
        logger.exception("Failed to hydrate RSS entry document %s", entity.platform_entity_id)
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
