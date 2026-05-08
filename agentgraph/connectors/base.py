"""Base connector interface and shared batch types."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Literal

from pydantic import BaseModel

# All resource_type values understood by the connector layer.
# Each value maps to a distinct fetch strategy within a connector.
ResourceType = Literal["channel", "dm", "document", "folder", "message", "spreadsheet", "thread"]

# All valid entity_type values stored in the DB.
ENTITY_TYPES: tuple[str, ...] = (
    "Channel",
    "Document",
    "Folder",
    "Message",
    "Person",
    "Spreadsheet",
    "Thread",
)

# Broad URL extractor — classify_url does fine-grained matching
_URL_RE = re.compile(r"https?://\S+")

# Maps ResourceType values to entity_type strings stored in the DB
RESOURCE_TYPE_TO_ENTITY_TYPE: dict[str, str] = {
    "channel":     "Channel",
    "dm":          "Channel",
    "document":    "Document",
    "folder":      "Folder",
    "message":     "Message",
    "spreadsheet": "Spreadsheet",
    "thread":      "Thread",
}


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
    is_stub: bool = False     # True → placeholder pending a full fetch; preserves synced_at=NULL


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

    def add_stubs_from(self, entity: EntityRecord) -> None:
        """Scan entity content for recognisable URLs and append stub EntityRecords and
        'references' EdgeRecords to this batch.

        Connectors call this after building each content-bearing entity so that
        linked resources from other platforms are visible in the graph before they
        are fetched.  Stub entities are inserted with synced_at=NULL so the
        relevant connector will do a full fetch when the resource is next visited.
        """
        if not entity.content:
            return
        from agentgraph.server.router import classify_url

        seen: set[str] = set()
        for raw_url in _URL_RE.findall(entity.content):
            ref = classify_url(raw_url)
            if ref is None:
                continue
            key = f"{ref.source}/{ref.resource_id}"
            if key in seen:
                continue
            # Skip self-references (e.g. a doc linking to itself)
            if ref.source == entity.platform and ref.resource_id == entity.platform_entity_id:
                continue
            seen.add(key)
            self.entities.append(EntityRecord(
                entity_type=RESOURCE_TYPE_TO_ENTITY_TYPE[ref.resource_type],
                platform=ref.source,
                platform_entity_id=ref.resource_id,
                is_stub=True,
            ))
            self.edges.append(EdgeRecord(
                edge_type="references",
                source_platform_entity_id=entity.platform_entity_id,
                target_platform_entity_id=ref.resource_id,
                platform="cross",
            ))


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
    source: ClassVar[str]           # platform name, e.g. "slack" — must be set by subclass
    fetch_policy: ClassVar[FetchPolicy]  # staleness policy — must be set by subclass

    poll_interval: ClassVar[timedelta | None] = None
    """Interval between background poll() calls. None disables polling for this connector."""

    # Auth integration — override in subclasses that support interactive auth.
    # auth_label deduplicates across connectors that share credentials (e.g. all Google connectors).
    auth_label: ClassVar[str | None] = None
    auth_description: ClassVar[str | None] = None
    onboard_prompt: ClassVar[str | None] = None

    @classmethod
    def run_auth_flow(cls) -> None:
        """Run the interactive authentication flow for this connector."""
        raise NotImplementedError(f"{cls.__name__} does not have an auth flow")

    @classmethod
    def get_authenticated_user(cls) -> str | None:
        """Return a display string for the currently authenticated user, or None."""
        return None

    @abstractmethod
    def can_handle(self, url: str) -> bool: ...

    @abstractmethod
    async def fetch(self, resource_type: ResourceType, resource_id: str, meta: dict[str, str] | None = None) -> EntityBatch: ...

    async def ingest(self) -> EntityBatch:
        """Run a one-shot bulk ingest of all available historical data for this connector.

        Override in connectors that support a full-history sweep beyond what poll() covers
        on first run (e.g. fetching all labels, not just inbox). The default no-ops so that
        connectors which don't need this remain unchanged.
        """
        return EntityBatch()

    async def poll(self, cursor: dict[str, Any]) -> tuple[EntityBatch, dict[str, Any]]:
        """Fetch all changes since cursor for background sync.

        cursor is {} on first call. Return (batch, updated_cursor).
        The SyncEngine persists the cursor between calls and upserts the returned batch.
        Connectors that handle upserting internally (e.g. by calling fetch()) should
        return an empty EntityBatch.
        """
        return EntityBatch(), cursor

    def entity_url(self, platform_entity_id: str) -> str | None:
        """Return the canonical web URL for an entity given its platform_entity_id.

        Used to populate metadata.web_url for entities that don't store it at
        ingest time. Return None if the URL cannot be derived from the ID alone
        (e.g. it requires metadata like guild_id or team_id).
        """
        return None

    async def last_synced_at(self, resource_id: str) -> datetime | None:
        """Return the most recent synced_at for a platform entity, or None."""
        from agentgraph.core.context import get_backend

        return await get_backend().get_last_synced_at(self.source, resource_id)
