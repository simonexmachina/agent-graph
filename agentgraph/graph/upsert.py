"""Idempotent upsert layer for entities and edges."""

from __future__ import annotations

import asyncio

from agentgraph.connectors.base import EntityBatch
from agentgraph.core.context import get_backend


async def upsert_batch(batch: EntityBatch) -> None:
    """Persist an EntityBatch to the graph, generating embeddings as needed."""
    person_embeddings, entity_embeddings = await asyncio.to_thread(_build_embeddings, batch)

    updated_entities = await get_backend().upsert_batch(batch, person_embeddings, entity_embeddings)
    from agentgraph.connectors.feed import (
        EntityUpdateMutation,
        entity_snapshot_from_entity,
        mutation_target_from_entity,
        notify_feed_connectors,
    )

    for entity in updated_entities:
        await notify_feed_connectors(
            EntityUpdateMutation(
                target=mutation_target_from_entity(entity),
                entity=entity_snapshot_from_entity(entity),
            )
        )
    await _link_references(batch)


def _build_embeddings(
    batch: EntityBatch,
) -> tuple[dict[str, list[float] | None], dict[str, list[float] | None]]:
    from agentgraph.graph.embeddings import encode_passage

    person_embeddings: dict[str, list[float] | None] = {}
    for p in batch.persons:
        canonical_key = p.canonical_email or f"{p.platform}:{p.platform_user_id}"
        text = " ".join(filter(None, [p.display_name, p.canonical_email]))
        vec: list[float] | None = encode_passage(text) if text else None
        person_embeddings[canonical_key] = vec
        person_embeddings[p.platform_user_id] = vec  # also indexed by user_id for edge resolution

    entity_embeddings: dict[str, list[float] | None] = {}
    for e in batch.entities:
        if not e.is_stub and e.content:
            text = f"{e.title or ''} {e.content}".strip()
            entity_embeddings[e.platform_entity_id] = encode_passage(text)
        else:
            entity_embeddings[e.platform_entity_id] = None

    return person_embeddings, entity_embeddings


async def _link_references(batch: EntityBatch) -> None:
    """After a batch is persisted, create cross-platform 'references' edges."""
    from agentgraph.graph.link import link_entity_to_urls

    for entity in batch.entities:
        if entity.content:
            await link_entity_to_urls(entity.platform_entity_id, entity.platform, entity.content)
