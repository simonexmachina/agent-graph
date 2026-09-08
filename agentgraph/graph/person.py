"""Person identity operations."""

from __future__ import annotations

from typing import Any

from agentgraph.core.context import get_backend
from agentgraph.core.storage import EntityResult
from agentgraph.graph.query import get_entity


async def unify_persons(
    primary_entity_id: str,
    duplicate_entity_ids: list[str],
) -> dict[str, Any]:
    """Merge duplicate Person entities into one canonical Person entity."""
    primary = await _resolve_person(primary_entity_id)
    duplicate_entities = [
        await _resolve_person(entity_id) for entity_id in duplicate_entity_ids
    ]
    duplicate_ids = [
        entity["id"]
        for entity in duplicate_entities
        if entity["id"] != primary["id"]
    ]
    updated = await get_backend().merge_person_entities(primary["id"], duplicate_ids)

    if duplicate_ids:
        from agentgraph.connectors.feed import (
            TombstoneMutation,
            mutation_target_from_entity,
            notify_feed_connectors,
        )
        from agentgraph.graph.upsert import notify_entity_upserts

        await notify_entity_upserts([updated])
        for duplicate in duplicate_entities:
            if duplicate["id"] != primary["id"]:
                await notify_feed_connectors(
                    TombstoneMutation(target=mutation_target_from_entity(duplicate))
                )
    return {
        "primary": updated,
        "merged_ids": duplicate_ids,
        "merged_count": len(duplicate_ids),
    }


async def _resolve_person(entity_id: str) -> EntityResult:
    entity = await get_entity(entity_id)
    if entity is None:
        raise ValueError(f"Entity {entity_id!r} not found")
    if entity["entity_type"] != "Person":
        raise ValueError(f"Entity {entity_id!r} is not a Person")
    return entity
