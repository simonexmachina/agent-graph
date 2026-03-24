"""Shared graph query layer used by both MCP tools and CLI commands."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from agentgraph.db.connection import get_pool
from agentgraph.graph.embeddings import encode


# ---------------------------------------------------------------------------
# Result types (plain dicts for easy JSON serialisation)
# ---------------------------------------------------------------------------

EntityResult = dict[str, Any]
EdgeResult = dict[str, Any]


# ---------------------------------------------------------------------------
# search_entities — hybrid vector + full-text search with RRF fusion
# ---------------------------------------------------------------------------

async def search_entities(
    query: str,
    entity_types: list[str] | None = None,
    limit: int = 10,
) -> list[EntityResult]:
    """
    Hybrid search: combines pgvector cosine similarity with full-text
    ts_rank via Reciprocal Rank Fusion (RRF, k=60).

    Returns up to `limit` entities ordered by fused score.
    """
    embedding = encode(query)
    embedding_str = str(embedding)

    pool = await get_pool()
    async with pool.acquire() as conn:
        type_filter = ""
        params: list[Any] = [embedding_str, query, limit * 5]

        if entity_types:
            type_filter = f"AND entity_type = ANY($4::text[])"
            params.append(entity_types)

        # RRF: score = 1/(k + rank_vector) + 1/(k + rank_fulltext)
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
                    coalesce(1.0 / (60 + f.rank), 0) AS score
                FROM vector_ranked v
                FULL OUTER JOIN fulltext_ranked f USING (id)
            )
            SELECT e.id, e.entity_type, e.platform, e.platform_entity_id,
                   e.title, e.content, e.metadata, e.created_at, e.updated_at,
                   fused.score
            FROM fused
            JOIN entities e ON e.id = fused.id
            ORDER BY fused.score DESC
            LIMIT $3
            """,
            *params,
        )
        return [_row_to_entity(row) for row in rows[:limit]]


# ---------------------------------------------------------------------------
# get_entity
# ---------------------------------------------------------------------------

async def get_entity(entity_id: str) -> EntityResult | None:
    """Fetch a single entity by its UUID string."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, entity_type, platform, platform_entity_id,
                   title, content, metadata, created_at, updated_at, synced_at
            FROM entities
            WHERE id = $1
            """,
            UUID(entity_id),
        )
    if row is None:
        return None
    return _row_to_entity(row)


# ---------------------------------------------------------------------------
# get_edges
# ---------------------------------------------------------------------------

async def get_edges(
    entity_id: str,
    edge_type: str | None = None,
    direction: str = "both",
) -> list[EdgeResult]:
    """
    Return edges connected to an entity.

    direction: 'in' | 'out' | 'both'
    """
    eid = UUID(entity_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        conditions: list[str] = []
        params: list[Any] = [eid]

        if direction in ("out", "both"):
            conditions.append("(e.source_entity_id = $1 OR e.source_person_id IN (SELECT id FROM persons WHERE id = $1))")
        if direction in ("in", "both"):
            conditions.append("(e.target_entity_id = $1 OR e.target_person_id IN (SELECT id FROM persons WHERE id = $1))")

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
                   e.source_entity_id, e.source_person_id,
                   e.target_entity_id, e.target_person_id,
                   se.platform_entity_id AS source_entity_ref,
                   te.platform_entity_id AS target_entity_ref,
                   sp.canonical_email    AS source_person_ref,
                   tp.canonical_email    AS target_person_ref
            FROM edges e
            LEFT JOIN entities se ON se.id = e.source_entity_id
            LEFT JOIN entities te ON te.id = e.target_entity_id
            LEFT JOIN persons  sp ON sp.id = e.source_person_id
            LEFT JOIN persons  tp ON tp.id = e.target_person_id
            WHERE ({where}) {type_clause}
            ORDER BY e.created_at DESC
            """,
            *params,
        )
        return [_row_to_edge(row) for row in rows]


# ---------------------------------------------------------------------------
# traverse_graph — BFS up to max_depth
# ---------------------------------------------------------------------------

async def traverse_graph(
    entity_id: str,
    max_depth: int = 2,
) -> dict[str, Any]:
    """
    BFS traversal from an entity. Returns nodes and edges up to max_depth.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        visited_entities: set[str] = set()
        frontier: list[str] = [entity_id]
        all_nodes: list[EntityResult] = []
        all_edges: list[EdgeResult] = []

        for _depth in range(max_depth):
            if not frontier:
                break

            placeholders = ", ".join(f"${i+1}" for i in range(len(frontier)))
            entity_uuids = [UUID(eid) for eid in frontier]

            # Fetch entities in frontier
            rows = await conn.fetch(
                f"""
                SELECT id, entity_type, platform, platform_entity_id,
                       title, content, metadata, created_at, updated_at
                FROM entities WHERE id IN ({placeholders})
                """,
                *entity_uuids,
            )
            for row in rows:
                eid_str = str(row["id"])
                if eid_str not in visited_entities:
                    visited_entities.add(eid_str)
                    all_nodes.append(_row_to_entity(row))

            # Fetch edges from frontier
            edge_rows = await conn.fetch(
                f"""
                SELECT e.id, e.edge_type, e.platform, e.properties,
                       e.source_entity_id, e.source_person_id,
                       e.target_entity_id, e.target_person_id,
                       se.platform_entity_id AS source_entity_ref,
                       te.platform_entity_id AS target_entity_ref
                FROM edges e
                LEFT JOIN entities se ON se.id = e.source_entity_id
                LEFT JOIN entities te ON te.id = e.target_entity_id
                WHERE e.source_entity_id IN ({placeholders})
                   OR e.target_entity_id IN ({placeholders})
                """,
                *entity_uuids, *entity_uuids,
            )
            next_frontier: list[str] = []
            for row in edge_rows:
                all_edges.append(_row_to_edge(row))
                for key in ("source_entity_id", "target_entity_id"):
                    val = row[key]
                    if val is not None:
                        val_str = str(val)
                        if val_str not in visited_entities:
                            next_frontier.append(val_str)

            frontier = list(set(next_frontier))

    return {"nodes": all_nodes, "edges": all_edges}


# ---------------------------------------------------------------------------
# query_by_filter
# ---------------------------------------------------------------------------

async def query_by_filter(
    entity_type: str,
    filters: dict[str, str],
    limit: int = 50,
) -> list[EntityResult]:
    """
    Return entities matching entity_type and optional metadata key=value filters.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        params: list[Any] = [entity_type, limit]
        meta_clauses: list[str] = []
        for k, v in filters.items():
            params.append(k)
            params.append(v)
            meta_clauses.append(f"metadata->>${len(params)-1} = ${len(params)}")

        where_meta = ("AND " + " AND ".join(meta_clauses)) if meta_clauses else ""
        rows = await conn.fetch(
            f"""
            SELECT id, entity_type, platform, platform_entity_id,
                   title, content, metadata, created_at, updated_at
            FROM entities
            WHERE entity_type = $1 {where_meta}
            ORDER BY last_accessed DESC
            LIMIT $2
            """,
            *params,
        )
        return [_row_to_entity(row) for row in rows]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _row_to_entity(row: Any) -> EntityResult:
    return {
        "id": str(row["id"]),
        "entity_type": row["entity_type"],
        "platform": row["platform"],
        "platform_entity_id": row["platform_entity_id"],
        "title": row["title"],
        "content": row["content"],
        "metadata": json.loads(row["metadata"]) if isinstance(row["metadata"], str) else dict(row["metadata"] or {}),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        "score": float(row["score"]) if "score" in row.keys() else None,
    }


def _row_to_edge(row: Any) -> EdgeResult:
    return {
        "id": str(row["id"]),
        "edge_type": row["edge_type"],
        "platform": row["platform"],
        "properties": json.loads(row["properties"]) if isinstance(row["properties"], str) else dict(row["properties"] or {}),
        "source_entity_id": str(row["source_entity_id"]) if row["source_entity_id"] else None,
        "source_person_id": str(row["source_person_id"]) if row["source_person_id"] else None,
        "target_entity_id": str(row["target_entity_id"]) if row["target_entity_id"] else None,
        "target_person_id": str(row["target_person_id"]) if row["target_person_id"] else None,
        "source_ref": row.get("source_entity_ref") or row.get("source_person_ref"),
        "target_ref": row.get("target_entity_ref") or row.get("target_person_ref"),
    }
