"""Bookmark graph entities to protect them from garbage collection."""

from __future__ import annotations

from agentgraph.core.context import get_backend
from agentgraph.core.storage import EntityResult
from agentgraph.graph.query import get_entity


async def bookmark_entity(entity_id: str) -> EntityResult:
    """Mark an entity as bookmarked by UUID, UUID prefix, or platform ref."""
    entity = await get_entity(entity_id)
    if entity is None:
        raise ValueError(f"Entity {entity_id!r} not found")
    return await get_backend().set_entity_bookmarked(entity["id"], True)
