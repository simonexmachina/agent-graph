"""SQLite + FTS5 storage backend."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from agentgraph.backends.sqlite.vector import (
    load_sqlite_vec,
    pack_embedding,
    vector_ranked,
)
from agentgraph.connectors.base import EntityBatch, EntityRecord, PersonRecord
from agentgraph.core.storage import EdgeResult, EntityResult, StorageBackend

logger = logging.getLogger(__name__)

_SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text()
_VALID_ORDER_BY = {"created_at", "updated_at", "last_accessed", "synced_at"}
_COLUMN_FILTERS = {"platform", "platform_entity_id", "entity_type"}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    return str(uuid.uuid4())


class SQLiteBackend(StorageBackend):
    def __init__(self, db_path: str = "~/.agentgraph/agentgraph.db", vector_mode: str = "sqlite-vec") -> None:
        self._db_path = str(Path(db_path).expanduser()) if db_path != ":memory:" else db_path
        self._vector_mode = vector_mode
        self._conn: aiosqlite.Connection | None = None
        self._vec_loaded = False
        # Serialises concurrent write transactions — SQLite only supports one writer at a time
        # and we use explicit BEGIN/COMMIT, so concurrent polls would deadlock without this.
        self._write_lock: asyncio.Lock | None = None

    async def initialize(self) -> None:
        self._write_lock = asyncio.Lock()

        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = await aiosqlite.connect(self._db_path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row

        if self._db_path != ":memory:":
            await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(_SCHEMA_SQL)

        if self._vector_mode == "sqlite-vec":
            self._vec_loaded = await load_sqlite_vec(self._conn)
            if self._vec_loaded:
                logger.info("sqlite-vec extension loaded")
            else:
                logger.info("sqlite-vec not available, falling back to numpy")

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    def _conn_or_raise(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("SQLiteBackend not initialized — call initialize() first")
        return self._conn

    # --- Internal helpers ---

    async def _fetchall(self, sql: str, params: list[Any] | None = None) -> list[Any]:
        conn = self._conn_or_raise()
        cursor = await conn.execute(sql, params or [])
        return await cursor.fetchall()

    async def _fetchone(self, sql: str, params: list[Any] | None = None) -> Any:
        conn = self._conn_or_raise()
        cursor = await conn.execute(sql, params or [])
        return await cursor.fetchone()

    async def _fetchval(self, sql: str, params: list[Any] | None = None) -> Any:
        row = await self._fetchone(sql, params)
        return row[0] if row else None

    async def _execute(self, sql: str, params: list[Any] | None = None) -> None:
        conn = self._conn_or_raise()
        await conn.execute(sql, params or [])

    # --- Write ---

    async def upsert_batch(
        self,
        batch: EntityBatch,
        person_embeddings: dict[str, list[float] | None],
        entity_embeddings: dict[str, list[float] | None],
    ) -> None:
        assert self._write_lock is not None
        async with self._write_lock:
            conn = self._conn_or_raise()
            await conn.execute("BEGIN")
            try:
                person_id_map = await self._upsert_persons(conn, batch.persons, person_embeddings)
                entity_id_map = await self._upsert_entities(conn, batch.entities, entity_embeddings)
                await self._upsert_edges(conn, batch, person_id_map, entity_id_map)
                await conn.execute("COMMIT")
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def _upsert_persons(
        self,
        conn: aiosqlite.Connection,
        persons: list[PersonRecord],
        embeddings: dict[str, list[float] | None],
    ) -> dict[str, str]:
        id_map: dict[str, str] = {}
        for p in persons:
            canonical_key = p.canonical_email or f"{p.platform}:{p.platform_user_id}"
            meta: dict[str, str] = {}
            if p.canonical_email:
                meta["canonical_email"] = p.canonical_email
            meta[f"{p.platform}_user_id"] = p.platform_user_id
            if p.platform_username:
                meta[f"{p.platform}_username"] = p.platform_username

            embedding = embeddings.get(canonical_key)
            emb_blob = pack_embedding(embedding) if embedding else None
            now = _now()

            cursor = await conn.execute(
                """
                INSERT INTO entities
                    (id, entity_type, platform, platform_entity_id, title, content,
                     content_embedding, metadata, last_accessed)
                VALUES (?, 'Person', 'canonical', ?, ?, ?, ?, ?, ?)
                ON CONFLICT (platform, platform_entity_id) DO UPDATE SET
                    title             = COALESCE(EXCLUDED.title, entities.title),
                    content           = COALESCE(EXCLUDED.content, entities.content),
                    content_embedding = COALESCE(EXCLUDED.content_embedding, entities.content_embedding),
                    metadata          = EXCLUDED.metadata,
                    last_accessed     = EXCLUDED.last_accessed
                RETURNING id
                """,
                [_new_id(), canonical_key, p.display_name, p.canonical_email,
                 emb_blob, json.dumps(meta), now],
            )
            row = await cursor.fetchone()
            entity_id: str = row[0]

            # Maintain FTS index
            await conn.execute("DELETE FROM entities_fts WHERE id = ?", [entity_id])
            if p.display_name or p.canonical_email:
                await conn.execute(
                    "INSERT INTO entities_fts (id, title, content) VALUES (?, ?, ?)",
                    [entity_id, p.display_name or "", p.canonical_email or ""],
                )

            id_map[p.platform_user_id] = entity_id
            if p.canonical_email:
                id_map[p.canonical_email] = entity_id
        return id_map

    async def _upsert_entities(
        self,
        conn: aiosqlite.Connection,
        entities: list[EntityRecord],
        embeddings: dict[str, list[float] | None],
    ) -> dict[str, str]:
        id_map: dict[str, str] = {}
        now = _now()
        for e in entities:
            if e.is_stub:
                cursor = await conn.execute(
                    """
                    INSERT INTO entities (id, entity_type, platform, platform_entity_id, last_accessed)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (platform, platform_entity_id) DO UPDATE SET
                        last_accessed = EXCLUDED.last_accessed
                    RETURNING id
                    """,
                    [_new_id(), e.entity_type, e.platform, e.platform_entity_id, now],
                )
            else:
                embedding = embeddings.get(e.platform_entity_id)
                emb_blob = pack_embedding(embedding) if embedding else None
                created = e.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if e.created_at else None
                updated = e.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ") if e.updated_at else None
                cursor = await conn.execute(
                    """
                    INSERT INTO entities
                        (id, entity_type, platform, platform_entity_id, title, content,
                         content_embedding, metadata, created_at, updated_at, synced_at, last_accessed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (platform, platform_entity_id) DO UPDATE SET
                        title             = COALESCE(EXCLUDED.title, entities.title),
                        content           = COALESCE(EXCLUDED.content, entities.content),
                        content_embedding = COALESCE(EXCLUDED.content_embedding, entities.content_embedding),
                        metadata          = EXCLUDED.metadata,
                        updated_at        = COALESCE(EXCLUDED.updated_at, entities.updated_at),
                        synced_at         = EXCLUDED.last_accessed,
                        last_accessed     = EXCLUDED.last_accessed
                    RETURNING id
                    """,
                    [_new_id(), e.entity_type, e.platform, e.platform_entity_id,
                     e.title, e.content, emb_blob, json.dumps(dict(e.metadata)),
                     created, updated, now, now],
                )

                # Maintain FTS index for non-stub entities
                row = await cursor.fetchone()
                entity_id: str = row[0]
                await conn.execute("DELETE FROM entities_fts WHERE id = ?", [entity_id])
                if e.title or e.content:
                    await conn.execute(
                        "INSERT INTO entities_fts (id, title, content) VALUES (?, ?, ?)",
                        [entity_id, e.title or "", e.content or ""],
                    )
                id_map[e.platform_entity_id] = entity_id
                continue

            row = await cursor.fetchone()
            id_map[e.platform_entity_id] = row[0]
        return id_map

    async def _upsert_edges(
        self,
        conn: aiosqlite.Connection,
        batch: EntityBatch,
        person_id_map: dict[str, str],
        entity_id_map: dict[str, str],
    ) -> None:
        now = _now()
        for edge in batch.edges:
            source_id: str | None = (
                entity_id_map.get(edge.source_platform_entity_id)
                if edge.source_platform_entity_id
                else person_id_map.get(edge.source_platform_user_id or "")
                if edge.source_platform_user_id
                else None
            )
            target_id: str | None = (
                entity_id_map.get(edge.target_platform_entity_id)
                if edge.target_platform_entity_id
                else person_id_map.get(edge.target_platform_user_id or "")
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
                INSERT INTO edges (id, edge_type, source_entity_id, target_entity_id, platform, properties, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (edge_type, source_entity_id, target_entity_id) DO NOTHING
                """,
                [_new_id(), edge.edge_type, source_id, target_id,
                 edge.platform, json.dumps(dict(edge.properties)), now],
            )

    # --- Read: entities ---

    async def search_entities(
        self,
        query_vec: list[float],
        query_text: str,
        entity_types: list[str] | None,
        limit: int,
        min_score: float,
    ) -> list[EntityResult]:
        conn = self._conn_or_raise()

        # BM25 via FTS5
        fts_ids: list[tuple[str, int]] = []
        try:
            type_clause = ""
            type_params: list[Any] = [query_text, limit * 5]
            if entity_types:
                placeholders = ",".join("?" * len(entity_types))
                type_clause = f"AND e.entity_type IN ({placeholders})"
                type_params = [query_text, *entity_types, limit * 5]

            cursor = await conn.execute(
                f"""
                SELECT e.id
                FROM entities_fts f
                JOIN entities e ON e.id = f.id
                WHERE entities_fts MATCH ? {type_clause}
                ORDER BY f.rank
                LIMIT ?
                """,
                type_params,
            )
            rows = await cursor.fetchall()
            fts_ids = [(row[0], i + 1) for i, row in enumerate(rows)]
        except Exception:
            pass

        # Vector search
        vec_ids = await vector_ranked(
            conn, query_vec, entity_types, limit, self._vector_mode, self._vec_loaded
        )

        # RRF fusion (k=60, fulltext weight=2x)
        # Rule: if BM25 found anything, include only results that BM25 also found.
        fts_set = {eid for eid, _ in fts_ids}
        vec_rank: dict[str, int] = {eid: rank for eid, rank in vec_ids}
        fts_rank: dict[str, int] = {eid: rank for eid, rank in fts_ids}

        candidates = fts_set if fts_set else set(vec_rank)
        if not candidates:
            return []

        scored: list[tuple[str, float]] = []
        for eid in candidates:
            score = 0.0
            if eid in vec_rank:
                score += 1.0 / (60 + vec_rank[eid])
            if eid in fts_rank:
                score += 2.0 / (60 + fts_rank[eid])
            scored.append((eid, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:limit]

        if not top:
            return []

        id_list = [eid for eid, _ in top]
        score_map = {eid: sc for eid, sc in top}
        placeholders = ",".join("?" * len(id_list))
        cursor = await conn.execute(
            f"""
            SELECT id, entity_type, platform, platform_entity_id,
                   title, content, metadata, created_at, updated_at
            FROM entities WHERE id IN ({placeholders})
            """,
            id_list,
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            r = _row_to_entity(row)
            r["score"] = score_map.get(r["id"], 0.0)
            if (r["score"] or 0) >= min_score:
                results.append(r)
        results.sort(key=lambda x: x.get("score") or 0, reverse=True)
        return results

    async def get_entity_by_id(self, entity_id: str) -> EntityResult | None:
        row = await self._fetchone(
            """
            SELECT id, entity_type, platform, platform_entity_id,
                   title, content, metadata, created_at, updated_at, synced_at
            FROM entities WHERE id = ?
            """,
            [entity_id],
        )
        return _row_to_entity(row) if row else None

    async def get_entities_by_id_prefix(self, prefix: str) -> list[EntityResult]:
        rows = await self._fetchall(
            """
            SELECT id, entity_type, platform, platform_entity_id,
                   title, content, metadata, created_at, updated_at, synced_at
            FROM entities WHERE id LIKE ?
            """,
            [f"{prefix}%"],
        )
        return [_row_to_entity(row) for row in rows]

    async def get_entity_by_platform(
        self, platform: str, platform_entity_id: str
    ) -> EntityResult | None:
        row = await self._fetchone(
            """
            SELECT id, entity_type, platform, platform_entity_id,
                   title, content, metadata, created_at, updated_at, synced_at
            FROM entities WHERE platform = ? AND platform_entity_id = ?
            """,
            [platform, platform_entity_id],
        )
        return _row_to_entity(row) if row else None

    async def list_entities(
        self,
        entity_types: list[str] | None,
        platform: str | None,
        since: datetime | None,
        limit: int,
    ) -> list[EntityResult]:
        clauses: list[str] = []
        params: list[Any] = []
        if entity_types:
            placeholders = ",".join("?" * len(entity_types))
            clauses.append(f"entity_type IN ({placeholders})")
            params.extend(entity_types)
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        if since:
            clauses.append("updated_at >= ?")
            params.append(since.strftime("%Y-%m-%dT%H:%M:%SZ"))
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = await self._fetchall(
            f"""
            SELECT id, entity_type, platform, platform_entity_id,
                   title, content, metadata, created_at, updated_at
            FROM entities
            {where}
            ORDER BY last_accessed DESC
            LIMIT ?
            """,
            params,
        )
        return [_row_to_entity(row) for row in rows]

    async def query_by_filter(
        self,
        entity_type: str,
        filters: dict[str, str],
        limit: int,
        order_by: str,
        since: datetime | None,
        authored_by: str | None,
        has_attachments: bool = False,
    ) -> list[EntityResult]:
        if order_by not in _VALID_ORDER_BY:
            order_by = "last_accessed"

        params: list[Any] = [entity_type]
        extra_clauses: list[str] = []
        for k, v in filters.items():
            if k in _COLUMN_FILTERS:
                extra_clauses.append(f"e.{k} = ?")
            else:
                extra_clauses.append(f"json_extract(e.metadata, '$.{k}') = ?")
            params.append(v)
        if since:
            extra_clauses.append("e.updated_at >= ?")
            params.append(since.strftime("%Y-%m-%dT%H:%M:%SZ"))
        if has_attachments:
            extra_clauses.append(
                "json_extract(e.metadata, '$.attachments') IS NOT NULL"
                " AND json_extract(e.metadata, '$.attachments') != '[]'"
            )

        authored_join = ""
        if authored_by:
            authored_join = """
            JOIN edges _auth ON _auth.edge_type = 'authored' AND _auth.target_entity_id = e.id
            JOIN entities _p ON _p.id = _auth.source_entity_id AND _p.entity_type = 'Person'
                AND (_p.platform_entity_id = ? OR json_extract(_p.metadata, '$.slack_user_id') = ?)
            """
            params.extend([authored_by, authored_by])

        where_extra = ("AND " + " AND ".join(extra_clauses)) if extra_clauses else ""
        params.append(limit)
        rows = await self._fetchall(
            f"""
            SELECT e.id, e.entity_type, e.platform, e.platform_entity_id,
                   e.title, e.content, e.metadata, e.created_at, e.updated_at
            FROM entities e
            {authored_join}
            WHERE e.entity_type = ? {where_extra}
            ORDER BY e.{order_by} DESC
            LIMIT ?
            """,
            params,
        )
        return [_row_to_entity(row) for row in rows]

    # --- Read: edges ---

    async def get_edges(
        self,
        entity_id: str,
        edge_type: str | None,
        direction: str,
    ) -> list[EdgeResult]:
        conditions: list[str] = []
        params: list[Any] = []
        if direction in ("out", "both"):
            conditions.append("e.source_entity_id = ?")
            params.append(entity_id)
        if direction in ("in", "both"):
            conditions.append("e.target_entity_id = ?")
            params.append(entity_id)
        if not conditions:
            return []

        type_clause = ""
        if edge_type:
            type_clause = "AND e.edge_type = ?"
            params.append(edge_type)

        where = " OR ".join(f"({c})" for c in conditions)
        rows = await self._fetchall(
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
            params,
        )
        return [_row_to_edge(row) for row in rows]

    async def get_edges_for_entities(self, entity_ids: list[str]) -> list[EdgeResult]:
        if not entity_ids:
            return []
        placeholders = ",".join("?" * len(entity_ids))
        rows = await self._fetchall(
            f"""
            SELECT e.id, e.edge_type, e.platform, e.properties,
                   e.source_entity_id, e.target_entity_id,
                   se.platform_entity_id AS source_ref,
                   te.platform_entity_id AS target_ref
            FROM edges e
            LEFT JOIN entities se ON se.id = e.source_entity_id
            LEFT JOIN entities te ON te.id = e.target_entity_id
            WHERE e.source_entity_id IN ({placeholders})
               OR e.target_entity_id IN ({placeholders})
            """,
            entity_ids + entity_ids,
        )
        return [_row_to_edge(row) for row in rows]

    async def traverse_graph(self, entity_id: str, max_depth: int) -> dict[str, Any]:
        conn = self._conn_or_raise()
        visited: set[str] = set()
        frontier: list[str] = [entity_id]
        all_nodes: list[EntityResult] = []
        all_edges: list[EdgeResult] = []

        for _ in range(max_depth):
            if not frontier:
                break
            placeholders = ",".join("?" * len(frontier))
            cursor = await conn.execute(
                f"""
                SELECT id, entity_type, platform, platform_entity_id,
                       title, content, metadata, created_at, updated_at
                FROM entities WHERE id IN ({placeholders})
                """,
                frontier,
            )
            for row in await cursor.fetchall():
                eid = row["id"]
                if eid not in visited:
                    visited.add(eid)
                    all_nodes.append(_row_to_entity(row))

            cursor = await conn.execute(
                f"""
                SELECT e.id, e.edge_type, e.platform, e.properties,
                       e.source_entity_id, e.target_entity_id,
                       se.platform_entity_id AS source_ref,
                       te.platform_entity_id AS target_ref
                FROM edges e
                LEFT JOIN entities se ON se.id = e.source_entity_id
                LEFT JOIN entities te ON te.id = e.target_entity_id
                WHERE e.source_entity_id IN ({placeholders})
                   OR e.target_entity_id IN ({placeholders})
                """,
                frontier + frontier,
            )
            next_frontier: list[str] = []
            for row in await cursor.fetchall():
                all_edges.append(_row_to_edge(row))
                for key in ("source_entity_id", "target_entity_id"):
                    val: str | None = row[key]
                    if val and val not in visited:
                        next_frontier.append(val)
            frontier = list(set(next_frontier))

        # Load final frontier
        unvisited = [eid for eid in frontier if eid not in visited]
        if unvisited:
            placeholders = ",".join("?" * len(unvisited))
            cursor = await conn.execute(
                f"""
                SELECT id, entity_type, platform, platform_entity_id,
                       title, content, metadata, created_at, updated_at
                FROM entities WHERE id IN ({placeholders})
                """,
                unvisited,
            )
            for row in await cursor.fetchall():
                all_nodes.append(_row_to_entity(row))

        return {"nodes": all_nodes, "edges": all_edges}

    # --- Linking ---

    async def find_entity_id(self, platform: str, platform_entity_id: str) -> str | None:
        return await self._fetchval(
            "SELECT id FROM entities WHERE platform = ? AND platform_entity_id = ?",
            [platform, platform_entity_id],
        )

    async def upsert_stub_entity(
        self, entity_type: str, platform: str, platform_entity_id: str
    ) -> str:
        cursor = await self._conn_or_raise().execute(
            """
            INSERT INTO entities (id, entity_type, platform, platform_entity_id, last_accessed)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (platform, platform_entity_id) DO UPDATE SET
                last_accessed = EXCLUDED.last_accessed
            RETURNING id
            """,
            [_new_id(), entity_type, platform, platform_entity_id, _now()],
        )
        row = await cursor.fetchone()
        return row[0]

    async def insert_references_edge(self, source_id: str, target_id: str) -> None:
        await self._execute(
            """
            INSERT INTO edges (id, edge_type, source_entity_id, target_entity_id, platform, properties)
            VALUES (?, 'references', ?, ?, 'cross', '{}')
            ON CONFLICT (edge_type, source_entity_id, target_entity_id) DO NOTHING
            """,
            [_new_id(), source_id, target_id],
        )

    async def find_entities_containing(
        self,
        text: str,
        exclude_platform: str,
        exclude_platform_entity_id: str,
    ) -> list[str]:
        rows = await self._fetchall(
            """
            SELECT id FROM entities
            WHERE content LIKE '%' || ? || '%'
              AND NOT (platform = ? AND platform_entity_id = ?)
            """,
            [text, exclude_platform, exclude_platform_entity_id],
        )
        return [row[0] for row in rows]

    # --- GC ---

    async def gc_entities(self, retention_days: int) -> int:
        cutoff = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        # SQLite doesn't have interval arithmetic; compute cutoff in Python
        from datetime import timedelta
        cutoff_dt = datetime.now(UTC) - timedelta(days=retention_days)
        cutoff = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        assert self._write_lock is not None
        async with self._write_lock:
            conn = self._conn_or_raise()
            await conn.execute("BEGIN")
            try:
                cursor = await conn.execute(
                    "SELECT id FROM entities WHERE last_accessed < ?", [cutoff]
                )
                to_delete = [row[0] for row in await cursor.fetchall()]
                if to_delete:
                    placeholders = ",".join("?" * len(to_delete))
                    await conn.execute(
                        f"DELETE FROM entities WHERE id IN ({placeholders})", to_delete
                    )
                    await conn.execute(
                        f"DELETE FROM entities_fts WHERE id IN ({placeholders})", to_delete
                    )
                await conn.execute("COMMIT")
            except Exception:
                await conn.execute("ROLLBACK")
                raise
        return len(to_delete)

    # --- Observations ---

    async def insert_observation(
        self,
        event_type: str,
        url: str,
        title: str | None,
        tab_id: int | None,
        timestamp: datetime,
        meta: str | None,
    ) -> None:
        ts_str = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
        dedup_cutoff = (timestamp.replace(second=max(0, timestamp.second - 2))).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        existing = await self._fetchval(
            """
            SELECT id FROM observations
            WHERE event_type = ? AND tab_id = ? AND url = ? AND timestamp >= ?
            LIMIT 1
            """,
            [event_type, tab_id, url, dedup_cutoff],
        )
        if existing:
            return
        await self._execute(
            """
            INSERT INTO observations (id, event_type, url, title, tab_id, timestamp, meta)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [_new_id(), event_type, url, title, tab_id, ts_str, meta],
        )

    async def patch_observation_meta(
        self,
        event_type: str,
        tab_id: int,
        url: str,
        meta: str,
    ) -> None:
        from datetime import timedelta
        cutoff = (datetime.now(UTC) - timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        obs_id = await self._fetchval(
            """
            SELECT id FROM observations
            WHERE event_type = ? AND tab_id = ? AND url = ? AND timestamp >= ? AND meta IS NULL
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            [event_type, tab_id, url, cutoff],
        )
        if obs_id:
            await self._execute(
                "UPDATE observations SET meta = ? WHERE id = ?",
                [meta, obs_id],
            )

    async def get_pending_observations(self, cutoff: datetime) -> list[dict[str, Any]]:
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = await self._fetchall(
            """
            SELECT o.id, o.url, o.tab_id, o.timestamp, o.meta
            FROM observations o
            WHERE o.event_type = 'focus'
              AND o.evaluated = 0
              AND o.timestamp < ?
              AND NOT EXISTS (
                  SELECT 1 FROM observations b
                  WHERE b.event_type = 'blur'
                    AND b.tab_id = o.tab_id
                    AND b.timestamp > o.timestamp
                    AND b.timestamp < ?
              )
            ORDER BY o.timestamp
            """,
            [cutoff_str, cutoff_str],
        )
        return [
            {
                "id": row["id"],
                "url": row["url"],
                "tab_id": row["tab_id"],
                "timestamp": datetime.fromisoformat(row["timestamp"]),
                "meta": row["meta"],
            }
            for row in rows
        ]

    async def mark_observation_evaluated(self, obs_id: str) -> None:
        await self._execute(
            "UPDATE observations SET evaluated = 1 WHERE id = ?", [obs_id]
        )

    # --- Sync state ---

    async def load_cursor(self, source: str) -> dict[str, Any]:
        val = await self._fetchval(
            "SELECT cursor FROM sync_state WHERE source = ?", [source]
        )
        return json.loads(val) if val else {}

    async def save_cursor(self, source: str, cursor: dict[str, Any]) -> None:
        await self._execute(
            """
            INSERT INTO sync_state (source, cursor, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT (source) DO UPDATE SET
                cursor = EXCLUDED.cursor,
                updated_at = EXCLUDED.updated_at
            """,
            [source, json.dumps(cursor), _now()],
        )

    # --- Connector support ---

    async def get_last_synced_at(
        self, platform: str, platform_entity_id: str
    ) -> datetime | None:
        val = await self._fetchval(
            """
            SELECT max(synced_at) FROM entities
            WHERE platform = ? AND platform_entity_id = ?
            """,
            [platform, platform_entity_id],
        )
        return datetime.fromisoformat(val) if val else None

    async def reset_synced_at(self, platform: str, platform_entity_id: str) -> None:
        await self._execute(
            "UPDATE entities SET synced_at = NULL WHERE platform = ? AND platform_entity_id = ?",
            [platform, platform_entity_id],
        )

    async def get_entity_type(self, platform: str, platform_entity_id: str) -> str | None:
        return await self._fetchval(
            "SELECT entity_type FROM entities WHERE platform = ? AND platform_entity_id = ?",
            [platform, platform_entity_id],
        )

    async def get_entity_platform_ref(self, entity_id: str) -> tuple[str, str] | None:
        row = await self._fetchone(
            "SELECT platform, platform_entity_id FROM entities WHERE id = ?",
            [entity_id],
        )
        if row is None:
            return None
        return (row["platform"], row["platform_entity_id"])


# --- Row serialization helpers ---

def _row_to_entity(row: Any) -> EntityResult:
    keys = row.keys() if hasattr(row, "keys") else []
    return {
        "id": row["id"],
        "entity_type": row["entity_type"],
        "platform": row["platform"],
        "platform_entity_id": row["platform_entity_id"],
        "title": row["title"],
        "content": row["content"],
        "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "score": row["score"] if "score" in keys else None,
    }


def _row_to_edge(row: Any) -> EdgeResult:
    return {
        "id": row["id"],
        "edge_type": row["edge_type"],
        "platform": row["platform"],
        "properties": json.loads(row["properties"]) if row["properties"] else {},
        "source_entity_id": row["source_entity_id"],
        "target_entity_id": row["target_entity_id"],
        "source_ref": row["source_ref"],
        "target_ref": row["target_ref"],
    }
