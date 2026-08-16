"""A type-checked starting point for a custom AgentGraph connector.

Register the class from this module through the ``agentgraph.connectors`` entry
point in your connector package's ``pyproject.toml``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, ClassVar

from agentgraph.connectors.base import (
    BaseConnector,
    EntityBatch,
    EntityRecord,
    FetchPolicy,
    ResourceType,
    SourceReference,
)
from agentgraph.graph.upsert import upsert_batch


class ExampleConnector(BaseConnector):
    """Connector skeleton for resources served from app.example.com."""

    source: ClassVar[str] = "example"
    fetch_policy: ClassVar[FetchPolicy] = FetchPolicy(stale_after_seconds=15 * 60)
    poll_interval: ClassVar[timedelta | None] = timedelta(minutes=10)
    url_patterns: ClassVar[list[str]] = ["https://app.example.com/*"]

    def can_handle(self, url: str) -> bool:
        return url.startswith("https://app.example.com/")

    def resolve_url(self, url: str) -> SourceReference | None:
        if not self.can_handle(url):
            return None
        resource_id = url.removeprefix("https://app.example.com/").split("?", maxsplit=1)[0]
        if not resource_id:
            return None
        return SourceReference(
            source=self.source,
            resource_type="document",
            resource_id=resource_id,
        )

    async def fetch(
        self,
        resource_type: ResourceType,
        resource_id: str,
        meta: dict[str, str] | None = None,
        account_id: str | None = None,
    ) -> EntityBatch:
        """Fetch one resource and persist its graph representation."""
        _ = (meta, account_id)
        last_sync = await self.last_synced_at(resource_id)
        if self.fetch_policy.decide(last_sync) == FetchPolicy.FRESH:
            return EntityBatch()

        since = last_sync.isoformat() if last_sync is not None else None
        batch = await fetch_example_resource(resource_type, resource_id, since=since)
        await upsert_batch(batch)
        return batch

    async def ingest(self, account_id: str | None = None) -> EntityBatch:
        """Backfill historical resources when the upstream API supports it."""
        _ = account_id
        batch = await fetch_full_history()
        await upsert_batch(batch)
        return batch

    async def poll(
        self,
        cursor: dict[str, Any],
        account_id: str | None = None,
    ) -> tuple[EntityBatch, dict[str, Any]]:
        """Fetch changes since the persisted cursor and return the next cursor."""
        _ = account_id
        cursor_value = cursor.get("cursor")
        start_cursor = cursor_value if isinstance(cursor_value, str) else None
        batch, next_cursor = await fetch_changes_since(start_cursor)
        return batch, {"cursor": next_cursor}


async def fetch_example_resource(
    resource_type: ResourceType,
    resource_id: str,
    since: str | None,
) -> EntityBatch:
    """Replace this placeholder with the upstream API request and mapping."""
    entity = EntityRecord(
        entity_type="Document",
        platform="example",
        platform_entity_id=resource_id,
        title=f"Example resource {resource_id}",
        metadata={"resource_type": resource_type, "since": since},
    )
    return EntityBatch(entities=[entity])


async def fetch_full_history() -> EntityBatch:
    """Replace with a paginated historical fetch when the API supports one."""
    return EntityBatch()


async def fetch_changes_since(cursor: str | None) -> tuple[EntityBatch, str]:
    """Replace with an incremental API request and its returned cursor."""
    return EntityBatch(), cursor or "initial-cursor"
