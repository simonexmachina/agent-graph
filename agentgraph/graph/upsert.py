"""Idempotent upsert layer for entities and edges."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from agentgraph.connectors.base import EdgeRecord, EntityBatch, EntityRecord, PersonRecord
from agentgraph.db.connection import get_pool
from agentgraph.graph.embeddings import encode

logger = logging.getLogger(__name__)


async def upsert_batch(batch: EntityBatch) -> None:
    """Persist an EntityBatch to the graph, generating embeddings as needed."""
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        person_id_map = await _upsert_persons(conn, batch.persons)
        entity_id_map = await _upsert_entities(conn, batch.entities)
        await _upsert_edges(conn, batch.edges, person_id_map, entity_id_map)

    await _link_references(batch)


async def _upsert_persons(
    conn: Any, persons: list[PersonRecord]
) -> dict[str, UUID]:
    """
    Upsert persons as Person entities (platform='canonical').
    Returns mapping of platform_user_id (and email if known) → entity UUID.
    """
    id_map: dict[str, UUID] = {}

    for p in persons:
        # Canonical key: email if known, else "<platform>:<user_id>"
        platform_entity_id = p.canonical_email or f"{p.platform}:{p.platform_user_id}"

        meta: dict[str, str] = {}
        if p.canonical_email:
            meta["canonical_email"] = p.canonical_email
        meta[f"{p.platform}_user_id"] = p.platform_user_id
        if p.platform_username:
            meta[f"{p.platform}_username"] = p.platform_username

        # Compute embedding from name + email so person entities rank well in search
        embedding_text = " ".join(filter(None, [p.display_name, p.canonical_email]))
        embedding: list[float] | None = encode(embedding_text) if embedding_text else None

        entity_id: UUID = await conn.fetchval(
            """
            INSERT INTO entities
                (entity_type, platform, platform_entity_id, title, content,
                 content_embedding, metadata)
            VALUES ('Person', 'canonical', $1, $2, $3, $4::vector, $5)
            ON CONFLICT (platform, platform_entity_id) DO UPDATE SET
                title             = COALESCE(EXCLUDED.title, entities.title),
                content           = COALESCE(EXCLUDED.content, entities.content),
                content_embedding = COALESCE(EXCLUDED.content_embedding, entities.content_embedding),
                metadata          = entities.metadata || EXCLUDED.metadata,
                last_accessed     = now()
            RETURNING id
            """,
            platform_entity_id,
            p.display_name,
            p.canonical_email,  # email as content for full-text search
            str(embedding) if embedding else None,
            json.dumps(meta),
        )

        id_map[p.platform_user_id] = entity_id
        if p.canonical_email:
            id_map[p.canonical_email] = entity_id

    return id_map


async def _upsert_entities(
    conn: Any, entities: list[EntityRecord]
) -> dict[str, UUID]:
    """
    Upsert entities with embeddings.
    Returns mapping of platform_entity_id → entity UUID.
    """
    id_map: dict[str, UUID] = {}

    for e in entities:
        if e.is_stub:
            # Stubs are placeholders pending a full fetch.  Insert with synced_at=NULL
            # so the connector treats the entity as never-synced when the resource is
            # next visited.  On conflict, only touch last_accessed — never overwrite
            # real content or advance synced_at.
            entity_id = await conn.fetchval(
                """
                INSERT INTO entities (entity_type, platform, platform_entity_id)
                VALUES ($1, $2, $3)
                ON CONFLICT (platform, platform_entity_id) DO UPDATE SET
                    last_accessed = now()
                RETURNING id
                """,
                e.entity_type,
                e.platform,
                e.platform_entity_id,
            )
        else:
            embedding: list[float] | None = None
            if e.content:
                text = f"{e.title or ''} {e.content}".strip()
                embedding = encode(text)

            entity_id = await conn.fetchval(
                """
                INSERT INTO entities
                    (entity_type, platform, platform_entity_id, title, content,
                     content_embedding, metadata, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6::vector, $7, $8, $9)
                ON CONFLICT (platform, platform_entity_id) DO UPDATE SET
                    title              = COALESCE(EXCLUDED.title, entities.title),
                    content            = COALESCE(EXCLUDED.content, entities.content),
                    content_embedding  = COALESCE(EXCLUDED.content_embedding, entities.content_embedding),
                    metadata           = entities.metadata || EXCLUDED.metadata,
                    updated_at         = COALESCE(EXCLUDED.updated_at, entities.updated_at),
                    synced_at          = now(),
                    last_accessed      = now()
                RETURNING id
                """,
                e.entity_type,
                e.platform,
                e.platform_entity_id,
                e.title,
                e.content,
                str(embedding) if embedding else None,
                json.dumps(dict(e.metadata)),
                e.created_at,
                e.updated_at,
            )

        id_map[e.platform_entity_id] = entity_id

    return id_map


async def _upsert_edges(
    conn: Any,
    edges: list[EdgeRecord],
    person_id_map: dict[str, UUID],
    entity_id_map: dict[str, UUID],
) -> None:
    for edge in edges:
        # Resolve source: entity takes priority, fall back to person
        source_entity_id: UUID | None = (
            entity_id_map.get(edge.source_platform_entity_id)
            if edge.source_platform_entity_id
            else person_id_map.get(edge.source_platform_user_id)
            if edge.source_platform_user_id
            else None
        )
        # Resolve target: entity takes priority, fall back to person
        target_entity_id: UUID | None = (
            entity_id_map.get(edge.target_platform_entity_id)
            if edge.target_platform_entity_id
            else person_id_map.get(edge.target_platform_user_id)
            if edge.target_platform_user_id
            else None
        )

        if not source_entity_id:
            logger.warning("Skipping edge %s — source not resolved", edge.edge_type)
            continue
        if not target_entity_id:
            logger.warning("Skipping edge %s — target not resolved", edge.edge_type)
            continue

        await conn.execute(
            """
            INSERT INTO edges
                (edge_type, source_entity_id, target_entity_id, platform, properties)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (edge_type, source_entity_id, target_entity_id) DO NOTHING
            """,
            edge.edge_type,
            source_entity_id,
            target_entity_id,
            edge.platform,
            json.dumps(dict(edge.properties)),
        )


async def _link_references(batch: EntityBatch) -> None:
    """After a batch is persisted, create cross-platform 'references' edges."""
    from agentgraph.graph.link import link_entity_from_content, link_entity_to_urls

    for entity in batch.entities:
        if entity.content:
            await link_entity_to_urls(entity.platform_entity_id, entity.platform, entity.content)
        await link_entity_from_content(entity.platform_entity_id, entity.platform)
