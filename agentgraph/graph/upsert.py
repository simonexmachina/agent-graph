"""Idempotent upsert layer for entities, persons, and edges."""

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
    async with pool.acquire() as conn:
        async with conn.transaction():
            person_id_map = await _upsert_persons(conn, batch.persons)
            entity_id_map = await _upsert_entities(conn, batch.entities)
            await _upsert_edges(conn, batch.edges, person_id_map, entity_id_map)


async def _upsert_persons(
    conn: Any, persons: list[PersonRecord]
) -> dict[str, UUID]:
    """
    Upsert persons and platform_identities.
    Returns mapping of platform_user_id → person UUID.
    """
    id_map: dict[str, UUID] = {}

    for p in persons:
        if p.canonical_email:
            # Known email: upsert by email
            person_id: UUID = await conn.fetchval(
                """
                INSERT INTO persons (canonical_email, display_name)
                VALUES ($1, $2)
                ON CONFLICT (canonical_email) DO UPDATE
                    SET display_name = COALESCE(EXCLUDED.display_name, persons.display_name),
                        last_accessed = now()
                RETURNING id
                """,
                p.canonical_email,
                p.display_name,
            )
        else:
            # Email-less identity: look up via existing platform identity first
            existing = await conn.fetchval(
                """
                SELECT person_id FROM platform_identities
                WHERE platform = $1 AND platform_user_id = $2
                """,
                p.platform,
                p.platform_user_id,
            )
            if existing:
                person_id = existing
                await conn.execute(
                    "UPDATE persons SET last_accessed = now() WHERE id = $1",
                    person_id,
                )
            else:
                person_id = await conn.fetchval(
                    "INSERT INTO persons (display_name) VALUES ($1) RETURNING id",
                    p.display_name,
                )

        # Upsert platform identity
        await conn.execute(
            """
            INSERT INTO platform_identities
                (person_id, platform, platform_user_id, platform_username)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (platform, platform_user_id) DO UPDATE
                SET platform_username = COALESCE(EXCLUDED.platform_username, platform_identities.platform_username)
            """,
            person_id,
            p.platform,
            p.platform_user_id,
            p.platform_username,
        )

        id_map[p.platform_user_id] = person_id

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
        embedding: list[float] | None = None
        if e.content:
            text = f"{e.title or ''} {e.content}".strip()
            embedding = encode(text)

        entity_id: UUID = await conn.fetchval(
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
        source_entity_id = (
            entity_id_map.get(edge.source_platform_entity_id)
            if edge.source_platform_entity_id
            else None
        )
        source_person_id = (
            person_id_map.get(edge.source_platform_user_id)
            if edge.source_platform_user_id
            else None
        )
        target_entity_id = (
            entity_id_map.get(edge.target_platform_entity_id)
            if edge.target_platform_entity_id
            else None
        )
        target_person_id = (
            person_id_map.get(edge.target_platform_user_id)
            if edge.target_platform_user_id
            else None
        )

        if not (source_entity_id or source_person_id):
            logger.warning("Skipping edge %s — source not resolved", edge.edge_type)
            continue
        if not (target_entity_id or target_person_id):
            logger.warning("Skipping edge %s — target not resolved", edge.edge_type)
            continue

        await conn.execute(
            """
            INSERT INTO edges
                (edge_type, source_entity_id, source_person_id,
                 target_entity_id, target_person_id, platform, properties)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            edge.edge_type,
            source_entity_id,
            source_person_id,
            target_entity_id,
            target_person_id,
            edge.platform,
            json.dumps(dict(edge.properties)),
        )
