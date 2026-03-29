"""Base connector interface and shared batch types."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel


class PersonRecord(BaseModel):
    platform: str
    platform_user_id: str
    platform_username: str | None = None
    canonical_email: str | None = None
    display_name: str | None = None


class EntityRecord(BaseModel):
    entity_type: str          # 'Message' | 'Document' | 'Channel' | 'Task'
    platform: str
    platform_entity_id: str
    title: str | None = None
    content: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, str | int | float | bool | None] = {}


class EdgeRecord(BaseModel):
    edge_type: str            # 'authored' | 'posted_in' | 'replied_to' | 'mentions'
    source_platform_entity_id: str | None = None
    source_platform_user_id: str | None = None
    target_platform_entity_id: str | None = None
    target_platform_user_id: str | None = None
    platform: str
    properties: dict[str, str | int | float | bool | None] = {}


class EntityBatch(BaseModel):
    entities: list[EntityRecord] = []
    edges: list[EdgeRecord] = []
    persons: list[PersonRecord] = []


class FetchPolicy:
    """Encapsulates refresh policy decisions for a resource."""

    FIRST_VISIT = "first_visit"
    INCREMENTAL = "incremental"
    FRESH = "fresh"

    def __init__(self, stale_after_seconds: int) -> None:
        self.stale_after = timedelta(seconds=stale_after_seconds)

    def decide(self, last_synced_at: datetime | None) -> str:
        """
        Return FIRST_VISIT, INCREMENTAL, or FRESH based on last sync time.
        - FIRST_VISIT: never synced
        - INCREMENTAL: synced but data is stale
        - FRESH: synced recently, only update last_accessed
        """
        if last_synced_at is None:
            return self.FIRST_VISIT
        age = datetime.now(UTC) - last_synced_at
        if age > self.stale_after:
            return self.INCREMENTAL
        return self.FRESH


class BaseConnector(ABC):
    source: str
    fetch_policy: FetchPolicy

    @abstractmethod
    def can_handle(self, url: str) -> bool: ...

    @abstractmethod
    async def fetch(self, resource_type: str, resource_id: str, meta: dict[str, str] | None = None) -> EntityBatch: ...

    async def last_synced_at(self, resource_id: str) -> datetime | None:
        """Return the most recent synced_at for a platform entity, or None."""
        from agentgraph.db.connection import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            result: Any = await conn.fetchval(
                """
                SELECT max(synced_at) FROM entities
                WHERE platform = $1 AND platform_entity_id = $2
                """,
                self.source,
                resource_id,
            )
        return result  # type: ignore[no-any-return]
