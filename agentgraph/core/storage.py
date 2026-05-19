"""StorageBackend ABC — the persistence-agnostic interface for AgentGraph."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from agentgraph.connectors.base import EntityBatch

EntityResult = dict[str, Any]
EdgeResult = dict[str, Any]


class StorageBackend(ABC):
    """Persistence-agnostic interface for the AgentGraph knowledge store.

    All methods are async. The backend is responsible for all SQL/storage
    operations; the graph layer computes embeddings and passes them in.
    """

    # --- Lifecycle ---

    @abstractmethod
    async def initialize(self) -> None:
        """Apply schema, run migrations, open connection pool."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release all connections and resources."""
        ...

    # --- Write ---

    @abstractmethod
    async def upsert_batch(
        self,
        batch: EntityBatch,
        person_embeddings: dict[str, list[float] | None],
        entity_embeddings: dict[str, list[float] | None],
    ) -> None:
        """Atomically persist an EntityBatch.

        person_embeddings: canonical_key (email or "platform:user_id") → vector
        entity_embeddings: platform_entity_id → vector
        """
        ...

    # --- Read: entities ---

    @abstractmethod
    async def search_entities(
        self,
        query_vec: list[float],
        query_text: str,
        entity_types: list[str] | None,
        limit: int,
        min_score: float,
        platform: str | None = None,
    ) -> list[EntityResult]: ...

    @abstractmethod
    async def get_entity_by_id(self, entity_id: str) -> EntityResult | None: ...

    @abstractmethod
    async def get_entities_by_ids(self, entity_ids: list[str]) -> list[EntityResult]: ...

    @abstractmethod
    async def get_entities_by_id_prefix(self, prefix: str) -> list[EntityResult]: ...

    @abstractmethod
    async def get_entity_by_platform(
        self, platform: str, platform_entity_id: str
    ) -> EntityResult | None: ...

    @abstractmethod
    async def list_entities(
        self,
        entity_types: list[str] | None,
        platform: str | None,
        since: datetime | None,
        limit: int,
    ) -> list[EntityResult]: ...

    @abstractmethod
    async def query_by_filter(
        self,
        entity_type: str,
        filters: dict[str, str],
        limit: int,
        order_by: str,
        since: datetime | None,
        authored_by: list[str] | None,
        has_attachments: bool = False,
    ) -> list[EntityResult]: ...

    # --- Read: edges ---

    @abstractmethod
    async def get_edges(
        self,
        entity_id: str,
        edge_type: str | None,
        direction: str,
    ) -> list[EdgeResult]: ...

    @abstractmethod
    async def get_edges_for_entities(self, entity_ids: list[str]) -> list[EdgeResult]: ...

    @abstractmethod
    async def traverse_graph(
        self, entity_id: str, max_depth: int
    ) -> dict[str, Any]: ...

    # --- Linking ---

    @abstractmethod
    async def find_entity_id(
        self, platform: str, platform_entity_id: str
    ) -> str | None: ...

    @abstractmethod
    async def upsert_stub_entity(
        self,
        entity_type: str,
        platform: str,
        platform_entity_id: str,
    ) -> str:
        """Insert a stub entity with synced_at=NULL. Returns internal UUID string."""
        ...

    @abstractmethod
    async def insert_references_edge(self, source_id: str, target_id: str) -> None: ...

    # --- GC ---

    @abstractmethod
    async def gc_entities(self, retention_days: int) -> int: ...

    # --- Sync state ---

    @abstractmethod
    async def load_cursor(self, source: str) -> dict[str, Any]: ...

    @abstractmethod
    async def save_cursor(self, source: str, cursor: dict[str, Any]) -> None: ...

    # --- Connector support ---

    @abstractmethod
    async def get_last_synced_at(
        self, platform: str, platform_entity_id: str
    ) -> datetime | None: ...

    @abstractmethod
    async def reset_synced_at(
        self, platform: str, platform_entity_id: str
    ) -> None: ...

    @abstractmethod
    async def touch_last_accessed(
        self, platform: str, platform_entity_id: str
    ) -> None: ...

    @abstractmethod
    async def touch_last_accessed_by_ids(self, entity_ids: list[str]) -> None: ...

    @abstractmethod
    async def get_entity_type(
        self, platform: str, platform_entity_id: str
    ) -> str | None: ...

    @abstractmethod
    async def get_entity_platform_ref(
        self, entity_id: str
    ) -> tuple[str, str] | None:
        """Return (platform, platform_entity_id) for an internal UUID, or None."""
        ...
