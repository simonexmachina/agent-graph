"""PostgreSQL + pgvector storage backend."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from agentgraph.connectors.base import EntityBatch, EntityRecord, PersonRecord
from agentgraph.core.storage import EdgeResult, EntityResult, StorageBackend

logger = logging.getLogger(__name__)

_SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text()
_MIGRATE_SQL = (Path(__file__).parent / "migrate_v2.sql").read_text()

_VALID_ORDER_BY = {"created_at", "updated_at", "last_accessed", "synced_at"}
_COLUMN_FILTERS = {"platform", "platform_entity_id", "entity_type"}


class PostgresBackend(StorageBackend):
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._pool: asyncpg.Pool | None = None  # type: ignore[type-arg]

    async def initialize(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._database_url,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        async with self._pool.acquire() as conn:
            await conn.execute(_SCHEMA_SQL)
            await conn.execute(_MIGRATE_SQL)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _pool_or_raise(self) -> asyncpg.Pool:  # type: ignore[type-arg]
        if self._pool is None:
            raise RuntimeError("PostgresBackend not initialized — call initialize() first")
        return self._pool

    # --- Write ---

    async def upsert_batch(
        self,
        batch: EntityBatch,
        person_embeddings: dict[str, list[float] | None],
        entity_embeddings: dict[str, list[float] | None],
    ) -> None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn, conn.transaction():
            person_id_map = await self._upsert_persons(conn, batch.persons, person_embeddings)
            entity_id_map = await self._upsert_entities(conn, batch.entities, entity_embeddings)
            await self._upsert_edges(conn, batch, person_id_map, entity_id_map)

    async def _upsert_persons(
        self,
        conn: Any,
        persons: list[PersonRecord],
        embeddings: dict[str, list[float] | None],
    ) -> dict[str, UUID]:
        id_map: dict[str, UUID] = {}
        for p in persons:
            canonical_key = p.canonical_email or f"{p.platform}:{p.platform_user_id}"
            meta: dict[str, str] = {}
            if p.canonical_email:
                meta["canonical_email"] = p.canonical_email
            meta[f"{p.platform}_user_id"] = p.platform_user_id
            if p.platform_username:
                meta[f"{p.platform}_username"] = p.platform_username

            embedding = embeddings.get(canonical_key)
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
                canonical_key,
                p.display_name,
                p.canonical_email,
                str(embedding) if embedding else None,
                json.dumps(meta),
            )
            id_map[p.platform_user_id] = entity_id
            if p.canonical_email:
                id_map[p.canonical_email] = entity_id
        return id_map

    async def _upsert_entities(
        self,
        conn: Any,
        entities: list[EntityRecord],
        embeddings: dict[str, list[float] | None],
    ) -> dict[str, UUID]:
        id_map: dict[str, UUID] = {}
        for e in entities:
            if e.is_stub:
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
                embedding = embeddings.get(e.platform_entity_id)
                entity_id = await conn.fetchval(
                    """
                    INSERT INTO entities
                        (entity_type, platform, platform_entity_id, title, content,
                         content_embedding, metadata, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6::vector, $7, $8, $9)
                    ON CONFLICT (platform, platform_entity_id) DO UPDATE SET
                        entity_type        = CASE WHEN entities.entity_type = 'Document' THEN EXCLUDED.entity_type ELSE entities.entity_type END,
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
        self,
        conn: Any,
        batch: EntityBatch,
        person_id_map: dict[str, UUID],
        entity_id_map: dict[str, UUID],
    ) -> None:
        for edge in batch.edges:
            source_id: UUID | None = (
                entity_id_map.get(edge.source_platform_entity_id)
                if edge.source_platform_entity_id
                else person_id_map.get(edge.source_platform_user_id)
                if edge.source_platform_user_id
                else None
            )
            target_id: UUID | None = (
                entity_id_map.get(edge.target_platform_entity_id)
                if edge.target_platform_entity_id
                else person_id_map.get(edge.target_platform_user_id)
                if edge.target_platform_user_id
                else None
            )
            if not source_id:
                logger.warning("Skipping edge %s — source not resolved", edge.edge_type)
                continue
            if not target_id:
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
                source_id,
                target_id,
                edge.platform,
                json.dumps(dict(edge.properties)),
            )

    # --- Read: entities ---

    async def search_entities(
        self,
        query_vec: list[float],
        query_text: str,
        entity_types: list[str] | None,
        limit: int,
        min_score: float,
        platform: str | None = None,
    ) -> list[EntityResult]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute("SET ivfflat.probes = 10")
            extra_filter = ""
            params: list[Any] = [str(query_vec), query_text, limit * 5]
            if entity_types:
                params.append(entity_types)
                extra_filter += f" AND entity_type = ANY(${len(params)}::text[])"
            if platform:
                params.append(platform)
                extra_filter += f" AND platform = ${len(params)}"
            type_filter = extra_filter

            rows = await conn.fetch(
                f"""
                WITH vector_ranked AS (
                    SELECT id,
                           row_number() OVER (ORDER BY content_embedding <=> $1::vector) AS rank
                    FROM entities
                    WHERE content_embedding IS NOT NULL
                    {type_filter}
                    LIMIT $3
                ),
                fulltext_ranked AS (
                    SELECT id,
                           row_number() OVER (
                               ORDER BY ts_rank(
                                   to_tsvector('english', coalesce(title,'') || ' ' || coalesce(content,'')),
                                   plainto_tsquery('english', $2)
                               ) DESC
                           ) AS rank
                    FROM entities
                    WHERE to_tsvector('english', coalesce(title,'') || ' ' || coalesce(content,''))
                          @@ plainto_tsquery('english', $2)
                    {type_filter}
                    LIMIT $3
                ),
                fused AS (
                    SELECT
                        coalesce(v.id, f.id) AS id,
                        coalesce(1.0 / (60 + v.rank), 0) +
                        coalesce(2.0 / (60 + f.rank), 0) AS score,
                        f.id IS NOT NULL AS has_fulltext
                    FROM vector_ranked v
                    FULL OUTER JOIN fulltext_ranked f USING (id)
                ),
                has_any_fulltext AS (SELECT EXISTS (SELECT 1 FROM fulltext_ranked)),
                filtered AS (
                    SELECT id, score FROM fused
                    WHERE has_fulltext OR NOT (SELECT * FROM has_any_fulltext)
                )
                SELECT e.id, e.entity_type, e.platform, e.platform_entity_id,
                       e.title, e.content, e.metadata, e.created_at, e.updated_at,
                       filtered.score
                FROM filtered
                JOIN entities e ON e.id = filtered.id
                ORDER BY filtered.score DESC
                LIMIT $3
                """,
                *params,
            )
            results = [_row_to_entity(row) for row in rows[:limit]]
            return [r for r in results if (r.get("score") or 0) >= min_score]

    async def get_entity_by_id(self, entity_id: str) -> EntityResult | None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, entity_type, platform, platform_entity_id,
                       title, content, metadata, created_at, updated_at, synced_at
                FROM entities WHERE id = $1
                """,
                UUID(entity_id),
            )
        return _row_to_entity(row) if row else None

    async def get_entities_by_ids(self, entity_ids: list[str]) -> list[EntityResult]:
        if not entity_ids:
            return []
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, entity_type, platform, platform_entity_id,
                       title, content, metadata, created_at, updated_at, synced_at
                FROM entities WHERE id = ANY($1::uuid[])
                """,
                entity_ids,
            )
        return [_row_to_entity(r) for r in rows]

    async def get_entities_by_id_prefix(self, prefix: str) -> list[EntityResult]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, entity_type, platform, platform_entity_id,
                       title, content, metadata, created_at, updated_at, synced_at
                FROM entities WHERE id::text LIKE $1
                """,
                f"{prefix}%",
            )
        return [_row_to_entity(row) for row in rows]

    async def get_entity_by_platform(
        self, platform: str, platform_entity_id: str
    ) -> EntityResult | None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, entity_type, platform, platform_entity_id,
                       title, content, metadata, created_at, updated_at, synced_at
                FROM entities WHERE platform = $1 AND platform_entity_id = $2
                """,
                platform,
                platform_entity_id,
            )
        return _row_to_entity(row) if row else None

    async def list_entities(
        self,
        entity_types: list[str] | None,
        platform: str | None,
        since: datetime | None,
        limit: int,
    ) -> list[EntityResult]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            params: list[Any] = [limit]
            clauses: list[str] = []
            if entity_types:
                params.append(entity_types)
                clauses.append(f"entity_type = ANY(${len(params)}::text[])")
            if platform:
                params.append(platform)
                clauses.append(f"platform = ${len(params)}")
            if since:
                params.append(since)
                clauses.append(f"updated_at >= ${len(params)}")
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = await conn.fetch(
                f"""
                SELECT id, entity_type, platform, platform_entity_id,
                       title, content, metadata, created_at, updated_at, synced_at
                FROM entities
                {where}
                ORDER BY last_accessed DESC NULLS LAST
                LIMIT $1
                """,
                *params,
            )
        return [_row_to_entity(row) for row in rows]

    async def query_by_filter(
        self,
        entity_type: str,
        filters: dict[str, str],
        limit: int,
        order_by: str,
        since: datetime | None,
        authored_by: list[str] | None,
        has_attachments: bool = False,
    ) -> list[EntityResult]:
        if order_by not in _VALID_ORDER_BY:
            order_by = "last_accessed"
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            params: list[Any] = [entity_type, limit]
            extra_clauses: list[str] = []
            for k, v in filters.items():
                if k in _COLUMN_FILTERS:
                    params.append(v)
                    extra_clauses.append(f"{k} = ${len(params)}")
                else:
                    params.append(v)
                    extra_clauses.append(f"metadata->>'{k}' = ${len(params)}")
            if since:
                params.append(since)
                extra_clauses.append(f"updated_at >= ${len(params)}")
            if has_attachments:
                extra_clauses.append(
                    "metadata->>'attachments' IS NOT NULL"
                    " AND metadata->>'attachments' != '[]'"
                )

            authored_join = ""
            if authored_by:
                placeholders: list[str] = []
                for user_id in authored_by:
                    params.append(user_id)
                    placeholders.append(f"${len(params)}")
                authored_join = f"""
                JOIN edges _auth ON _auth.edge_type = 'authored'
                    AND _auth.target_entity_id = e.id
                JOIN entities _p ON _p.id = _auth.source_entity_id
                    AND _p.entity_type = 'Person'
                    AND _p.platform_entity_id IN ({", ".join(placeholders)})
                """

            where_extra = ("AND " + " AND ".join(extra_clauses)) if extra_clauses else ""
            rows = await conn.fetch(
                f"""
                SELECT e.id, e.entity_type, e.platform, e.platform_entity_id,
                       e.title, e.content, e.metadata, e.created_at, e.updated_at
                FROM entities e
                {authored_join}
                WHERE e.entity_type = $1 {where_extra}
                ORDER BY e.{order_by} DESC NULLS LAST
                LIMIT $2
                """,
                *params,
            )
        return [_row_to_entity(row) for row in rows]

    # --- Read: edges ---

    async def get_edges(
        self,
        entity_id: str,
        edge_type: str | None,
        direction: str,
    ) -> list[EdgeResult]:
        eid = UUID(entity_id)
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            conditions: list[str] = []
            params: list[Any] = [eid]
            if direction in ("out", "both"):
                conditions.append("e.source_entity_id = $1")
            if direction in ("in", "both"):
                conditions.append("e.target_entity_id = $1")
            if not conditions:
                return []
            type_clause = ""
            if edge_type:
                params.append(edge_type)
                type_clause = f"AND e.edge_type = ${len(params)}"
            where = " OR ".join(conditions)
            rows = await conn.fetch(
                f"""
                SELECT e.id, e.edge_type, e.platform, e.properties,
                       e.source_entity_id, e.target_entity_id,
                       se.platform_entity_id AS source_ref,
                       te.platform_entity_id AS target_ref
                FROM edges e
                LEFT JOIN entities se ON se.id = e.source_entity_id
                LEFT JOIN entities te ON te.id = e.target_entity_id
                WHERE ({where}) {type_clause}
                ORDER BY e.created_at DESC
                """,
                *params,
            )
        return [_row_to_edge(row) for row in rows]

    async def get_edges_for_entities(self, entity_ids: list[str]) -> list[EdgeResult]:
        if not entity_ids:
            return []
        uuids = [UUID(eid) for eid in entity_ids]
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT e.id, e.edge_type, e.platform, e.properties,
                       e.source_entity_id, e.target_entity_id,
                       se.platform_entity_id AS source_ref,
                       te.platform_entity_id AS target_ref
                FROM edges e
                LEFT JOIN entities se ON se.id = e.source_entity_id
                LEFT JOIN entities te ON te.id = e.target_entity_id
                WHERE e.source_entity_id = ANY($1::uuid[])
                   OR e.target_entity_id = ANY($1::uuid[])
                """,
                uuids,
            )
        return [_row_to_edge(row) for row in rows]

    async def traverse_graph(
        self, entity_id: str, max_depth: int
    ) -> dict[str, Any]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            visited: set[str] = set()
            frontier: list[str] = [entity_id]
            all_nodes: list[EntityResult] = []
            all_edges: list[EdgeResult] = []

            for _ in range(max_depth):
                if not frontier:
                    break
                uuids = [UUID(eid) for eid in frontier]
                rows = await conn.fetch(
                    """
                    SELECT id, entity_type, platform, platform_entity_id,
                           title, content, metadata, created_at, updated_at
                    FROM entities WHERE id = ANY($1::uuid[])
                    """,
                    uuids,
                )
                for row in rows:
                    s = str(row["id"])
                    if s not in visited:
                        visited.add(s)
                        all_nodes.append(_row_to_entity(row))

                edge_rows = await conn.fetch(
                    """
                    SELECT e.id, e.edge_type, e.platform, e.properties,
                           e.source_entity_id, e.target_entity_id,
                           se.platform_entity_id AS source_ref,
                           te.platform_entity_id AS target_ref
                    FROM edges e
                    LEFT JOIN entities se ON se.id = e.source_entity_id
                    LEFT JOIN entities te ON te.id = e.target_entity_id
                    WHERE e.source_entity_id = ANY($1::uuid[])
                       OR e.target_entity_id = ANY($1::uuid[])
                    """,
                    uuids,
                )
                next_frontier: list[str] = []
                for row in edge_rows:
                    all_edges.append(_row_to_edge(row))
                    for key in ("source_entity_id", "target_entity_id"):
                        val = row[key]
                        if val is not None:
                            s = str(val)
                            if s not in visited:
                                next_frontier.append(s)
                frontier = list(set(next_frontier))

            # Load final frontier entities
            unvisited = [eid for eid in frontier if eid not in visited]
            if unvisited:
                rows = await conn.fetch(
                    """
                    SELECT id, entity_type, platform, platform_entity_id,
                           title, content, metadata, created_at, updated_at
                    FROM entities WHERE id = ANY($1::uuid[])
                    """,
                    [UUID(eid) for eid in unvisited],
                )
                for row in rows:
                    all_nodes.append(_row_to_entity(row))

        return {"nodes": all_nodes, "edges": all_edges}

    # --- Linking ---

    async def find_entity_id(
        self, platform: str, platform_entity_id: str
    ) -> str | None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            val = await conn.fetchval(
                "SELECT id FROM entities WHERE platform = $1 AND platform_entity_id = $2",
                platform,
                platform_entity_id,
            )
        return str(val) if val else None

    async def upsert_stub_entity(
        self, entity_type: str, platform: str, platform_entity_id: str
    ) -> str:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            val = await conn.fetchval(
                """
                INSERT INTO entities (entity_type, platform, platform_entity_id, synced_at)
                VALUES ($1, $2, $3, NULL)
                ON CONFLICT (platform, platform_entity_id) DO UPDATE
                    SET last_accessed = now()
                RETURNING id
                """,
                entity_type,
                platform,
                platform_entity_id,
            )
        return str(val)

    async def insert_references_edge(self, source_id: str, target_id: str) -> None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO edges
                    (edge_type, source_entity_id, target_entity_id, platform, properties)
                VALUES ('references', $1, $2, 'cross', $3)
                ON CONFLICT (edge_type, source_entity_id, target_entity_id) DO NOTHING
                """,
                UUID(source_id),
                UUID(target_id),
                json.dumps({}),
            )

    # --- GC ---

    async def gc_entities(self, retention_days: int) -> int:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn, conn.transaction():
            count: int = await conn.fetchval(
                """
                WITH deleted AS (
                    DELETE FROM entities
                    WHERE last_accessed < now() - ($1 || ' days')::interval
                    RETURNING id
                )
                SELECT count(*) FROM deleted
                """,
                str(retention_days),
            )
        return count

    # --- Observations ---

    # --- Sync state ---

    async def load_cursor(self, source: str) -> dict[str, Any]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT cursor FROM sync_state WHERE source = $1",
                source,
            )
        if not row:
            return {}
        val = row["cursor"]
        return json.loads(val) if isinstance(val, str) else dict(val)

    async def save_cursor(self, source: str, cursor: dict[str, Any]) -> None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sync_state (source, cursor, updated_at)
                VALUES ($1, $2::jsonb, now())
                ON CONFLICT (source) DO UPDATE
                    SET cursor = EXCLUDED.cursor, updated_at = now()
                """,
                source,
                json.dumps(cursor),
            )

    # --- Connector support ---

    async def get_last_synced_at(
        self, platform: str, platform_entity_id: str
    ) -> datetime | None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            result: datetime | None = await conn.fetchval(
                """
                SELECT max(synced_at) FROM entities
                WHERE platform = $1 AND platform_entity_id = $2
                """,
                platform,
                platform_entity_id,
            )
        return result

    async def reset_synced_at(
        self, platform: str, platform_entity_id: str
    ) -> None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE entities SET synced_at = NULL WHERE platform = $1 AND platform_entity_id = $2",
                platform,
                platform_entity_id,
            )

    async def touch_last_accessed(
        self, platform: str, platform_entity_id: str
    ) -> None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE entities SET last_accessed = now() WHERE platform = $1 AND platform_entity_id = $2",
                platform,
                platform_entity_id,
            )

    async def touch_last_accessed_by_ids(self, entity_ids: list[str]) -> None:
        if not entity_ids:
            return
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE entities SET last_accessed = now() WHERE id = ANY($1::uuid[])",
                entity_ids,
            )

    async def get_entity_type(
        self, platform: str, platform_entity_id: str
    ) -> str | None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            return await conn.fetchval(  # type: ignore[no-any-return]
                "SELECT entity_type FROM entities WHERE platform = $1 AND platform_entity_id = $2",
                platform,
                platform_entity_id,
            )

    async def get_entity_platform_ref(
        self, entity_id: str
    ) -> tuple[str, str] | None:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT platform, platform_entity_id FROM entities WHERE id = $1::uuid",
                entity_id,
            )
        if row is None:
            return None
        return (row["platform"], row["platform_entity_id"])


# --- Row serialization helpers ---

def _row_to_entity(row: Any) -> EntityResult:
    return {
        "id": str(row["id"]),
        "entity_type": row["entity_type"],
        "platform": row["platform"],
        "platform_entity_id": row["platform_entity_id"],
        "title": row["title"],
        "content": row["content"],
        "metadata": (
            json.loads(row["metadata"])
            if isinstance(row["metadata"], str)
            else dict(row["metadata"] or {})
        ),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        "synced_at": row["synced_at"].isoformat() if row.get("synced_at") else None,
        "score": float(row["score"]) if "score" in row else None,
    }


def _row_to_edge(row: Any) -> EdgeResult:
    return {
        "id": str(row["id"]),
        "edge_type": row["edge_type"],
        "platform": row["platform"],
        "properties": (
            json.loads(row["properties"])
            if isinstance(row["properties"], str)
            else dict(row["properties"] or {})
        ),
        "source_entity_id": str(row["source_entity_id"]) if row["source_entity_id"] else None,
        "target_entity_id": str(row["target_entity_id"]) if row["target_entity_id"] else None,
        "source_ref": row.get("source_ref"),
        "target_ref": row.get("target_ref"),
    }
