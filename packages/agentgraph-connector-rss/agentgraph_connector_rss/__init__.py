"""RSS and Atom connector."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, cast

from agentgraph.connectors.base import (
    BaseConnector,
    ConnectorAccount,
    EdgeRecord,
    EntityBatch,
    EntityRecord,
    FetchPolicy,
    ResourceType,
)
from agentgraph_connector_rss.auth import (
    add_feed_urls,
    list_rss_accounts,
    load_rss_creds,
    preview_feed,
    run_rss_flow,
    verify_rss_auth,
)

_STALE_AFTER = 30 * 60


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
            creds = load_rss_creds()
        except RuntimeError:
            return None
        return creds.label or "RSS"

    @classmethod
    def list_accounts(cls) -> list[ConnectorAccount]:
        return [
            ConnectorAccount(
                account_id=str(account["account_id"]),
                label=str(account["label"]),
                auth_group=cls.auth_label or cls.source,
                source=cls.source,
                metadata={
                    "feed_count": str(account.get("feed_count") or "0"),
                },
            )
            for account in list_rss_accounts()
        ]

    @classmethod
    async def verify_auth(cls, account_id: str | None = None) -> tuple[str, str | None]:
        return await verify_rss_auth(account_id)

    @classmethod
    def run_cli_command(cls, args: list[str]) -> dict[str, Any]:
        if not args:
            raise ValueError("Usage: agentgraph connector rss add <feed-url> [feed-url...]")
        command, *rest = args
        if command != "add":
            raise ValueError(f"Unknown rss connector command '{command}'. Available: add")
        creds = add_feed_urls(rest)
        return {
            "status": "ok",
            "source": cls.source,
            "account_id": creds.account_id,
            "feed_urls": creds.feed_urls,
            "added": rest,
        }

    def can_handle(self, url: str) -> bool:
        try:
            creds = load_rss_creds()
        except RuntimeError:
            return False
        return url in creds.feed_urls

    async def ingest(self, account_id: str | None = None) -> EntityBatch:
        creds = load_rss_creds(account_id)
        combined = EntityBatch()
        for feed_url in creds.feed_urls:
            batch = await _fetch_feed(feed_url)
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
        return EntityBatch()


async def _fetch_feed(feed_url: str) -> EntityBatch:
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
            metadata={"feed_url": feed_url},
        )
    ]
    edges: list[EdgeRecord] = []
    batch = EntityBatch()

    for raw_entry in cast(list[Any], parsed.entries):
        entry = cast(dict[str, Any], raw_entry)
        entity = _entry_to_entity(feed_url, feed_entity_id, entry)
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
