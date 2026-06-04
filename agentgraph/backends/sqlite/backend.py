"""SQLite + FTS5 storage backend."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import asyncio
import json
import logging
import re
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

_FTS5_SPECIAL = re.compile(r'[^\w\s]', re.UNICODE)


def _fts5_query(text: str) -> str:
    """Strip FTS5 syntax characters so arbitrary user text doesn't cause parse errors."""
    return _FTS5_SPECIAL.sub(" ", text).strip()
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

        await self._run_migrations()

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

    async def _run_migrations(self) -> None:
        conn = self._conn_or_raise()
        cursor = await conn.execute("PRAGMA table_info(entities)")
        columns = {row["name"] for row in await cursor.fetchall()}
        if "cumulative_dwell_ms" not in columns:
            await conn.execute(
                "ALTER TABLE entities ADD COLUMN cumulative_dwell_ms INTEGER NOT NULL DEFAULT 0"
            )

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

    async def _resolve_existing_entity_id(
        self,
        conn: aiosqlite.Connection,
        platform: str,
        platform_entity_id: str,
    ) -> str | None:
        cursor = await conn.execute(
            "SELECT id FROM entities WHERE platform = ? AND platform_entity_id = ?",
            [platform, platform_entity_id],
        )
        row = await cursor.fetchone()
        return str(row[0]) if row else None

    async def _resolve_existing_person_id(
        self,
        conn: aiosqlite.Connection,
        platform: str,
        platform_user_id: str,
    ) -> str | None:
        cursor = await conn.execute(
            """
            SELECT id
            FROM entities
            WHERE entity_type = 'Person'
              AND platform = 'canonical'
              AND json_extract(metadata, ?) = ?
            """,
            [f"$.{platform}_user_id", platform_user_id],
        )
        row = await cursor.fetchone()
        return str(row[0]) if row else None

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

            existing_id = await self._resolve_person_for_upsert(
                conn, canonical_key, p.platform, p.platform_user_id
            )
            if existing_id is not None:
                await conn.execute(
                    """
                    UPDATE entities
                    SET title = COALESCE(?, title),
                        content = COALESCE(?, content),
                        content_embedding = COALESCE(?, content_embedding),
                        metadata = json_patch(metadata, ?),
                        last_accessed = ?
                    WHERE id = ?
                    """,
                    [p.display_name, p.canonical_email, emb_blob, json.dumps(meta), now, existing_id],
                )
                entity_id = existing_id
            else:
                cursor = await conn.execute(
                    """
                    INSERT INTO entities
                        (id, entity_type, platform, platform_entity_id, title, content,
                         content_embedding, metadata, last_accessed)
                    VALUES (?, 'Person', 'canonical', ?, ?, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    [
                        _new_id(),
                        canonical_key,
                        p.display_name,
                        p.canonical_email,
                        emb_blob,
                        json.dumps(meta),
                        now,
                    ],
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError("Failed to upsert person entity")
                entity_id = str(row[0])

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

    async def _resolve_person_for_upsert(
        self,
        conn: aiosqlite.Connection,
        canonical_key: str,
        platform: str,
        platform_user_id: str,
    ) -> str | None:
        cursor = await conn.execute(
            """
            SELECT id
            FROM entities
            WHERE entity_type = 'Person'
              AND platform = 'canonical'
              AND platform_entity_id = ?
            """,
            [canonical_key],
        )
        row = await cursor.fetchone()
        if row:
            return str(row[0])
        return await self._resolve_existing_person_id(conn, platform, platform_user_id)

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
                        entity_type       = CASE WHEN entities.entity_type = 'Document' THEN EXCLUDED.entity_type ELSE entities.entity_type END,
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
                if row is None:
                    raise RuntimeError(f"Failed to upsert entity {e.platform}:{e.platform_entity_id}")
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
            if row is None:
                raise RuntimeError(f"Failed to upsert stub entity {e.platform}:{e.platform_entity_id}")
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
            if not source_id:
                if edge.source_platform_entity_id:
                    source_id = await self._resolve_existing_entity_id(
                        conn, edge.platform, edge.source_platform_entity_id
                    )
                elif edge.source_platform_user_id:
                    source_id = await self._resolve_existing_person_id(
                        conn, edge.platform, edge.source_platform_user_id
                    )
            target_id: str | None = (
                entity_id_map.get(edge.target_platform_entity_id)
                if edge.target_platform_entity_id
                else person_id_map.get(edge.target_platform_user_id or "")
                if edge.target_platform_user_id
                else None
            )
            if not target_id:
                if edge.target_platform_entity_id:
                    target_id = await self._resolve_existing_entity_id(
                        conn, edge.platform, edge.target_platform_entity_id
                    )
                elif edge.target_platform_user_id:
                    target_id = await self._resolve_existing_person_id(
                        conn, edge.platform, edge.target_platform_user_id
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

    async def merge_person_entities(
        self,
        primary_entity_id: str,
        duplicate_entity_ids: list[str],
    ) -> EntityResult:
        duplicate_ids = [eid for eid in duplicate_entity_ids if eid != primary_entity_id]
        if not duplicate_ids:
            entity = await self.get_entity_by_id(primary_entity_id)
            if entity is None:
                raise ValueError(f"Entity {primary_entity_id!r} not found")
            if entity["entity_type"] != "Person":
                raise ValueError(f"Entity {primary_entity_id!r} is not a Person")
            return entity

        assert self._write_lock is not None
        async with self._write_lock:
            conn = self._conn_or_raise()
            await conn.execute("BEGIN")
            try:
                all_ids = [primary_entity_id, *duplicate_ids]
                placeholders = ",".join("?" * len(all_ids))
                cursor = await conn.execute(
                    f"""
                    SELECT id, entity_type, platform, platform_entity_id,
                           title, content, metadata, last_accessed
                    FROM entities
                    WHERE id IN ({placeholders})
                    """,
                    all_ids,
                )
                rows = await cursor.fetchall()
                by_id = {str(row["id"]): row for row in rows}
                missing = [eid for eid in all_ids if eid not in by_id]
                if missing:
                    raise ValueError(f"Person entity not found: {missing[0]}")
                for eid, row in by_id.items():
                    if row["entity_type"] != "Person":
                        raise ValueError(f"Entity {eid!r} is not a Person")

                primary = by_id[primary_entity_id]
                merged_metadata: dict[str, Any] = {}
                for eid in duplicate_ids:
                    merged_metadata.update(json.loads(by_id[eid]["metadata"] or "{}"))
                merged_metadata.update(json.loads(primary["metadata"] or "{}"))

                title = primary["title"] or next(
                    (by_id[eid]["title"] for eid in duplicate_ids if by_id[eid]["title"]),
                    None,
                )
                content = primary["content"] or next(
                    (by_id[eid]["content"] for eid in duplicate_ids if by_id[eid]["content"]),
                    None,
                )
                last_accessed_values = [
                    value for value in (by_id[eid]["last_accessed"] for eid in all_ids) if value
                ]
                last_accessed = max(last_accessed_values) if last_accessed_values else _now()

                await conn.execute(
                    """
                    UPDATE entities
                    SET title = ?, content = ?, metadata = ?, last_accessed = ?
                    WHERE id = ?
                    """,
                    [title, content, json.dumps(merged_metadata), last_accessed, primary_entity_id],
                )

                dup_placeholders = ",".join("?" * len(duplicate_ids))
                await conn.execute(
                    f"""
                    UPDATE OR IGNORE edges
                    SET source_entity_id = ?
                    WHERE source_entity_id IN ({dup_placeholders})
                    """,
                    [primary_entity_id, *duplicate_ids],
                )
                await conn.execute(
                    f"DELETE FROM edges WHERE source_entity_id IN ({dup_placeholders})",
                    duplicate_ids,
                )
                await conn.execute(
                    f"""
                    UPDATE OR IGNORE edges
                    SET target_entity_id = ?
                    WHERE target_entity_id IN ({dup_placeholders})
                    """,
                    [primary_entity_id, *duplicate_ids],
                )
                await conn.execute(
                    f"DELETE FROM edges WHERE target_entity_id IN ({dup_placeholders})",
                    duplicate_ids,
                )
                await conn.execute(
                    "DELETE FROM edges WHERE source_entity_id = ? AND target_entity_id = ?",
                    [primary_entity_id, primary_entity_id],
                )
                await conn.execute(
                    f"DELETE FROM entities_fts WHERE id IN ({','.join('?' * len(all_ids))})",
                    all_ids,
                )
                await conn.execute(
                    f"DELETE FROM entities WHERE id IN ({dup_placeholders})",
                    duplicate_ids,
                )
                if title or content:
                    await conn.execute(
                        "INSERT INTO entities_fts (id, title, content) VALUES (?, ?, ?)",
                        [primary_entity_id, title or "", content or ""],
                    )
                await conn.execute("COMMIT")
            except Exception:
                await conn.execute("ROLLBACK")
                raise

        entity = await self.get_entity_by_id(primary_entity_id)
        if entity is None:
            raise RuntimeError("Merged primary person disappeared")
        return entity

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
        conn = self._conn_or_raise()

        # BM25 via FTS5
        fts_ids: list[tuple[str, int]] = []
        try:
            extra_clause = ""
            fts_extra_params: list[Any] = []
            if entity_types:
                placeholders = ",".join("?" * len(entity_types))
                extra_clause += f" AND e.entity_type IN ({placeholders})"
                fts_extra_params.extend(entity_types)
            if platform:
                extra_clause += " AND e.platform = ?"
                fts_extra_params.append(platform)

            cursor = await conn.execute(
                f"""
                SELECT e.id
                FROM entities_fts f
                JOIN entities e ON e.id = f.id
                WHERE entities_fts MATCH ? {extra_clause}
                ORDER BY f.rank
                LIMIT ?
                """,
                [_fts5_query(query_text), *fts_extra_params, limit * 5],
            )
            rows = await cursor.fetchall()
            fts_ids = [(row[0], i + 1) for i, row in enumerate(rows)]
        except Exception:
            pass

        # Vector search
        vec_ids = await vector_ranked(
            conn, query_vec, entity_types, limit, self._vector_mode, self._vec_loaded,
            platform=platform,
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

        import math

        id_list = [eid for eid, _ in top]
        score_map = {eid: sc for eid, sc in top}
        placeholders = ",".join("?" * len(id_list))
        cursor = await conn.execute(
            f"""
            SELECT id, entity_type, platform, platform_entity_id,
                   title, content, metadata, created_at, updated_at, synced_at, last_accessed, cumulative_dwell_ms
            FROM entities WHERE id IN ({placeholders})
            """,
            id_list,
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            r = _row_to_entity(row)
            base_score = score_map.get(r["id"], 0.0)
            dwell_ms = r.get("cumulative_dwell_ms", 0)
            dwell_boost = 0.1 * math.log10(1 + (dwell_ms / 1000.0))
            r["score"] = base_score + dwell_boost

            if (r["score"] or 0) >= min_score:
                results.append(r)
        results.sort(key=lambda x: x.get("score") or 0, reverse=True)
        return results

    async def get_entity_by_id(self, entity_id: str) -> EntityResult | None:
        row = await self._fetchone(
            """
            SELECT id, entity_type, platform, platform_entity_id,
                   title, content, metadata, created_at, updated_at, synced_at, last_accessed, cumulative_dwell_ms
            FROM entities WHERE id = ?
            """,
            [entity_id],
        )
        return _row_to_entity(row) if row else None

    async def get_entities_by_ids(self, entity_ids: list[str]) -> list[EntityResult]:
        if not entity_ids:
            return []
        placeholders = ",".join("?" * len(entity_ids))
        rows = await self._fetchall(
            f"""
            SELECT id, entity_type, platform, platform_entity_id,
                   title, content, metadata, created_at, updated_at, synced_at, last_accessed, cumulative_dwell_ms
            FROM entities WHERE id IN ({placeholders})
            """,
            entity_ids,
        )
        return [_row_to_entity(r) for r in rows]

    async def get_entities_by_id_prefix(self, prefix: str) -> list[EntityResult]:
        rows = await self._fetchall(
            """
            SELECT id, entity_type, platform, platform_entity_id,
                   title, content, metadata, created_at, updated_at, synced_at, last_accessed, cumulative_dwell_ms
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
                   title, content, metadata, created_at, updated_at, synced_at, last_accessed, cumulative_dwell_ms
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
                   title, content, metadata, created_at, updated_at, synced_at, last_accessed, cumulative_dwell_ms
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
        authored_by: list[str] | None,
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
        authored_params: list[Any] = []
        if authored_by:
            placeholders = ", ".join("?" for _ in authored_by)
            metadata_placeholders = ", ".join("?" for _ in authored_by)
            authored_join = f"""
            JOIN edges _auth ON _auth.edge_type = 'authored' AND _auth.target_entity_id = e.id
            JOIN entities _p ON _p.id = _auth.source_entity_id AND _p.entity_type = 'Person'
                AND (
                    _p.platform_entity_id IN ({placeholders})
                    OR EXISTS (
                        SELECT 1 FROM json_each(_p.metadata)
                        WHERE json_each.value IN ({metadata_placeholders})
                    )
                )
            """
            authored_params.extend([*authored_by, *authored_by])

        where_extra = ("AND " + " AND ".join(extra_clauses)) if extra_clauses else ""
        params.append(limit)
        rows = await self._fetchall(
            f"""
            SELECT e.id, e.entity_type, e.platform, e.platform_entity_id,
                   e.title, e.content, e.metadata, e.created_at, e.updated_at, e.cumulative_dwell_ms
            FROM entities e
            {authored_join}
            WHERE e.entity_type = ? {where_extra}
            ORDER BY e.{order_by} DESC
            LIMIT ?
            """,
            [*authored_params, *params],
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
                       title, content, metadata, created_at, updated_at, synced_at, last_accessed
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
                       title, content, metadata, created_at, updated_at, synced_at, last_accessed
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
        if row is None:
            raise RuntimeError(f"Failed to upsert stub entity {platform}:{platform_entity_id}")
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

    async def increment_dwell_time(
        self, platform: str, platform_entity_id: str, dwell_ms: int
    ) -> None:
        await self._execute(
            """
            UPDATE entities
            SET cumulative_dwell_ms = cumulative_dwell_ms + ?
            WHERE platform = ? AND platform_entity_id = ?
            """,
            [dwell_ms, platform, platform_entity_id],
        )

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

    async def get_platform_last_synced_at(self, platform: str) -> datetime | None:
        val = await self._fetchval(
            """
            SELECT max(synced_at) FROM entities
            WHERE platform = ?
            """,
            [platform],
        )
        return datetime.fromisoformat(val) if val else None

    async def reset_synced_at(self, platform: str, platform_entity_id: str) -> None:
        await self._execute(
            "UPDATE entities SET synced_at = NULL WHERE platform = ? AND platform_entity_id = ?",
            [platform, platform_entity_id],
        )

    async def touch_last_accessed(self, platform: str, platform_entity_id: str) -> None:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        await self._execute(
            "UPDATE entities SET last_accessed = ? WHERE platform = ? AND platform_entity_id = ?",
            [now, platform, platform_entity_id],
        )

    async def touch_last_accessed_by_ids(self, entity_ids: list[str]) -> None:
        if not entity_ids:
            return
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        placeholders = ",".join("?" * len(entity_ids))
        await self._execute(
            f"UPDATE entities SET last_accessed = ? WHERE id IN ({placeholders})",
            [now, *entity_ids],
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
        "synced_at": row["synced_at"] if "synced_at" in keys else None,
        "last_accessed": row["last_accessed"] if "last_accessed" in keys else None,
        "cumulative_dwell_ms": row["cumulative_dwell_ms"] if "cumulative_dwell_ms" in keys else 0,
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
