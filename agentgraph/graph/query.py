"""Shared graph query layer used by both MCP tools and CLI commands."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import json
from datetime import UTC
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
    min_score: float = 0.03,
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
        # Increase ivfflat probe count so approximate search covers enough
        # of the index to reliably find nearest neighbours (default probes=1
        # only scans ~1% of lists=100, causing false misses at low rank).
        await conn.execute("SET ivfflat.probes = 10")

        type_filter = ""
        params: list[Any] = [embedding_str, query, limit * 5]

        if entity_types:
            type_filter = "AND entity_type = ANY($4::text[])"
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


# ---------------------------------------------------------------------------
# get_entity
# ---------------------------------------------------------------------------

async def get_entity(entity_id: str) -> EntityResult | None:
    """Fetch a single entity by UUID, unambiguous UUID prefix, or platform ref.

    Platform ref formats accepted:
      - ``"{platform}/{platform_entity_id}"``
      - ``"{platform}/{resource_type}/{platform_entity_id}"``  (resource_type ignored)
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Full UUID — exact match
        if len(entity_id) == 36 or (len(entity_id) == 32 and "-" not in entity_id):
            row = await conn.fetchrow(
                """
                SELECT id, entity_type, platform, platform_entity_id,
                       title, content, metadata, created_at, updated_at, synced_at
                FROM entities WHERE id = $1
                """,
                UUID(entity_id),
            )
        # Platform ref: "platform/entity_id" or "platform/resource_type/entity_id"
        elif "/" in entity_id:
            parts = entity_id.split("/")
            platform_hint = parts[0]
            entity_id_hint = parts[-1]
            row = await conn.fetchrow(
                """
                SELECT id, entity_type, platform, platform_entity_id,
                       title, content, metadata, created_at, updated_at, synced_at
                FROM entities WHERE platform = $1 AND platform_entity_id = $2
                """,
                platform_hint,
                entity_id_hint,
            )
        else:
            # UUID prefix match — must be unambiguous
            rows = await conn.fetch(
                """
                SELECT id, entity_type, platform, platform_entity_id,
                       title, content, metadata, created_at, updated_at, synced_at
                FROM entities WHERE id::text LIKE $1
                """,
                f"{entity_id}%",
            )
            if len(rows) > 1:
                raise ValueError(
                    f"Ambiguous prefix {entity_id!r} matches {len(rows)} entities"
                )
            row = rows[0] if rows else None
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

            entity_uuids = [UUID(eid) for eid in frontier]

            # Fetch entities in frontier
            rows = await conn.fetch(
                """
                SELECT id, entity_type, platform, platform_entity_id,
                       title, content, metadata, created_at, updated_at
                FROM entities WHERE id = ANY($1::uuid[])
                """,
                list(entity_uuids),
            )
            for row in rows:
                eid_str = str(row["id"])
                if eid_str not in visited_entities:
                    visited_entities.add(eid_str)
                    all_nodes.append(_row_to_entity(row))

            # Fetch edges from frontier
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
                list(entity_uuids),
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

        # Fetch the final frontier's entities (discovered but not yet loaded)
        unvisited = [eid for eid in frontier if eid not in visited_entities]
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


# ---------------------------------------------------------------------------
# query_by_filter
# ---------------------------------------------------------------------------

_COLUMN_FILTERS = {"platform", "platform_entity_id", "entity_type"}
_VALID_ORDER_BY = {"created_at", "updated_at", "last_accessed", "synced_at"}


async def query_by_filter(
    entity_type: str,
    filters: dict[str, str],
    limit: int = 50,
    order_by: str = "last_accessed",
    since: str | None = None,
    authored_by_me: bool = False,
) -> list[EntityResult]:
    """
    Return entities matching entity_type and optional filters.

    Filters whose key matches a known column (platform, platform_entity_id,
    entity_type) are applied as column equality checks; all others are applied
    as metadata JSONB lookups.  ``since`` accepts an ISO timestamp or a relative
    duration like ``12h``, ``30m``, ``2d``.  ``authored_by_me`` filters to
    entities with an ``authored`` edge from the current user (resolved from
    stored credentials).
    """
    if order_by not in _VALID_ORDER_BY:
        order_by = "last_accessed"

    pool = await get_pool()
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
            cutoff = _parse_since(since)
            params.append(cutoff)
            extra_clauses.append(f"created_at >= ${len(params)}")

        authored_join = ""
        if authored_by_me:
            me = _resolve_me()
            if me:
                params.append(me)
                authored_join = f"""
                JOIN edges _auth ON _auth.edge_type = 'authored'
                    AND _auth.target_entity_id = e.id
                JOIN entities _p ON _p.id = _auth.source_entity_id
                    AND _p.entity_type = 'Person'
                    AND (_p.platform_entity_id = ${len(params)}
                         OR _p.metadata->>'slack_user_id' = ${len(params)})
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


async def list_entities(
    entity_types: list[str] | None = None,
    platform: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[EntityResult]:
    """List entities by recency with optional type/platform/time filters."""
    pool = await get_pool()
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
            cutoff = _parse_since(since)
            params.append(cutoff)
            clauses.append(f"created_at >= ${len(params)}")

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = await conn.fetch(
            f"""
            SELECT id, entity_type, platform, platform_entity_id,
                   title, content, metadata, created_at, updated_at
            FROM entities
            {where}
            ORDER BY last_accessed DESC NULLS LAST
            LIMIT $1
            """,
            *params,
        )
        return [_row_to_entity(row) for row in rows]


async def get_edges_for_entities(entity_ids: list[str]) -> list[EdgeResult]:
    """Fetch all edges touching any of the given entity IDs."""
    if not entity_ids:
        return []
    uuids = [UUID(eid) for eid in entity_ids]
    pool = await get_pool()
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


def _resolve_me() -> str | None:
    """Return the current user's email or Slack user ID from the configured provider."""
    from agentgraph.auth.credentials import load as load_creds
    from agentgraph.auth.google_provider import get_provider

    email = get_provider().get_user_email()
    if email:
        return email
    stored = load_creds()
    if stored.slack and stored.slack.user_id:
        return stored.slack.user_id
    return None


def _parse_since(since: str) -> Any:
    """Parse a relative duration (12h, 30m, 2d) or ISO timestamp string."""
    import re
    from datetime import datetime, timedelta

    m = re.fullmatch(r"(\d+)(h|m|d)", since.strip())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"h": timedelta(hours=n), "m": timedelta(minutes=n), "d": timedelta(days=n)}[unit]
        return datetime.now(UTC) - delta
    return datetime.fromisoformat(since)


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
        "score": float(row["score"]) if "score" in row else None,
    }


def _row_to_edge(row: Any) -> EdgeResult:
    return {
        "id": str(row["id"]),
        "edge_type": row["edge_type"],
        "platform": row["platform"],
        "properties": json.loads(row["properties"]) if isinstance(row["properties"], str) else dict(row["properties"] or {}),
        "source_entity_id": str(row["source_entity_id"]) if row["source_entity_id"] else None,
        "target_entity_id": str(row["target_entity_id"]) if row["target_entity_id"] else None,
        "source_ref": row.get("source_ref"),
        "target_ref": row.get("target_ref"),
    }
