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
from agentgraph.perf import timed

logger = logging.getLogger(__name__)

_SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text()

_FTS5_SPECIAL = re.compile(r"[^\w\s]", re.UNICODE)


def _fts5_query(text: str) -> str:
    """Strip FTS5 syntax characters so arbitrary user text doesn't cause parse errors."""
    return _FTS5_SPECIAL.sub(" ", text).strip()


_VALID_ORDER_BY = {
    "created_at",
    "updated_at",
    "source_created_at",
    "source_updated_at",
    "observed_at",
    "synced_at",
}
_LIST_PAGE_ORDER_BY = {
    **{field: field for field in _VALID_ORDER_BY},
    "display_name": """
        COALESCE(
            NULLIF(TRIM(title), ''),
            NULLIF(TRIM(json_extract(metadata, '$.display_name')), ''),
            NULLIF(TRIM(json_extract(metadata, '$.canonical_email')), ''),
            NULLIF(TRIM(content), ''),
            platform_entity_id,
            id
        ) COLLATE NOCASE
    """,
    "entity_type": "entity_type COLLATE NOCASE",
    "platform": "platform COLLATE NOCASE",
}
_COLUMN_FILTERS = {"platform", "platform_entity_id", "entity_type"}
_FTS_DELETE_CHUNK_SIZE = 500


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    return str(uuid.uuid4())


def _append_merged_people(
    metadata: dict[str, Any],
    merged_people: list[dict[str, str]],
    merged_person_ids: set[str],
) -> None:
    """Append valid, previously merged Person summaries without duplication."""
    existing_merged_people = metadata.get("merged_people", [])
    if not isinstance(existing_merged_people, list):
        return
    for existing_person in existing_merged_people:
        if not isinstance(existing_person, dict):
            continue
        existing_id = existing_person.get("id")
        existing_title = existing_person.get("title")
        existing_ref = existing_person.get("platform_entity_id")
        if (
            not isinstance(existing_id, str)
            or not isinstance(existing_title, str)
            or not isinstance(existing_ref, str)
            or existing_id in merged_person_ids
        ):
            continue
        merged_people.append(
            {
                "id": existing_id,
                "title": existing_title,
                "platform_entity_id": existing_ref,
            }
        )
        merged_person_ids.add(existing_id)


class SQLiteBackend(StorageBackend):
    def __init__(
        self, db_path: str = "~/.agentgraph/agentgraph.db", vector_mode: str = "sqlite-vec"
    ) -> None:
        self._db_path = str(Path(db_path).expanduser()) if db_path != ":memory:" else db_path
        self._vector_mode = vector_mode
        self._conn: aiosqlite.Connection | None = None
        self._read_conn: aiosqlite.Connection | None = None
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
        if self._db_path == ":memory:":
            self._read_conn = self._conn

        if self._db_path != ":memory:":
            await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        legacy_table = await self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'entities'"
        )
        if await legacy_table.fetchone():
            cursor = await self._conn.execute("PRAGMA table_info(entities)")
            existing_columns = {row["name"] for row in await cursor.fetchall()}
            if "observed_at" not in existing_columns:
                await self._conn.execute("ALTER TABLE entities ADD COLUMN observed_at TEXT")
        await self._conn.executescript(_SCHEMA_SQL)

        await self._run_migrations()

        if self._db_path != ":memory:":
            self._read_conn = await aiosqlite.connect(self._db_path, isolation_level=None)
            self._read_conn.row_factory = sqlite3.Row
            await self._read_conn.execute("PRAGMA foreign_keys=ON")

        if self._vector_mode == "sqlite-vec":
            assert self._read_conn is not None
            self._vec_loaded = await load_sqlite_vec(self._read_conn)
            if self._vec_loaded:
                logger.info("sqlite-vec extension loaded")
            else:
                logger.info("sqlite-vec not available, falling back to numpy")

    async def close(self) -> None:
        if self._read_conn is not None and self._read_conn is not self._conn:
            await self._read_conn.close()
            self._read_conn = None
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
        self._read_conn = None

    def _conn_or_raise(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("SQLiteBackend not initialized — call initialize() first")
        return self._conn

    def _read_conn_or_raise(self) -> aiosqlite.Connection:
        if self._read_conn is None:
            raise RuntimeError("SQLiteBackend not initialized — call initialize() first")
        return self._read_conn

    # --- Internal helpers ---

    async def _run_migrations(self) -> None:
        conn = self._conn_or_raise()
        cursor = await conn.execute("PRAGMA table_info(entities)")
        entity_columns = {
            str(row["name"]): bool(row["notnull"]) for row in await cursor.fetchall()
        }
        columns = set(entity_columns)
        if "cumulative_dwell_ms" not in columns:
            await conn.execute(
                "ALTER TABLE entities ADD COLUMN cumulative_dwell_ms INTEGER NOT NULL DEFAULT 0"
            )
        if "bookmarked" not in columns:
            await conn.execute(
                "ALTER TABLE entities ADD COLUMN bookmarked INTEGER NOT NULL DEFAULT 0"
            )
        if "observed_at" not in columns:
            await conn.execute("ALTER TABLE entities ADD COLUMN observed_at TEXT")
            entity_columns["observed_at"] = False
        needs_retention_migration = (
            "last_accessed" in columns
            or not entity_columns.get("created_at", False)
            or not entity_columns.get("updated_at", False)
            or entity_columns.get("observed_at", False)
            or "source_created_at" not in columns
            or "source_updated_at" not in columns
            or "retention_policy" not in columns
            or "retention_parent_id" not in columns
        )
        if needs_retention_migration:
            await self._rebuild_entities_for_retention(columns)
        await conn.execute(
            "UPDATE entities SET entity_type = 'Email' WHERE entity_type = 'Thread'"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_bookmarked ON entities(bookmarked)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_platform_synced_at ON entities(platform, synced_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_observed_at ON entities(observed_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_observed_at_id ON entities(observed_at DESC, id ASC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_type_observed_at ON entities(entity_type, observed_at DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_type_observed_at_id ON entities(entity_type, observed_at DESC, id ASC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_type_created_at ON entities(entity_type, created_at DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_type_updated_at ON entities(entity_type, updated_at DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_type_source_created_at ON entities(entity_type, source_created_at DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_type_source_updated_at ON entities(entity_type, source_updated_at DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_retention_parent ON entities(retention_parent_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_platform_observed_at_id ON entities(platform, observed_at DESC, id ASC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_platform_type_observed_at ON entities(platform, entity_type, observed_at DESC)"
        )

    async def _rebuild_entities_for_retention(self, columns: set[str]) -> None:
        """Best-effort migration from source-based timestamps to lifecycle timestamps."""
        conn = self._conn_or_raise()
        now_sql = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
        if "source_created_at" in columns:
            local_created = f"COALESCE(created_at, {now_sql})"
            source_created = "source_created_at"
        else:
            legacy_access = "last_accessed, " if "last_accessed" in columns else ""
            local_created = f"COALESCE(observed_at, {legacy_access}synced_at, {now_sql})"
            source_created = "created_at" if "created_at" in columns else "NULL"

        if "source_updated_at" in columns:
            local_updated = f"COALESCE(updated_at, {local_created})"
            source_updated = "source_updated_at"
        else:
            local_updated = (
                "CASE "
                "WHEN synced_at IS NOT NULL AND synced_at > COALESCE(observed_at, '') "
                "THEN synced_at "
                f"ELSE {local_created} END"
            )
            source_updated = "updated_at" if "updated_at" in columns else "NULL"

        if "retention_policy" in columns:
            retention_policy = "retention_policy"
        else:
            retention_policy = (
                "CASE entity_type WHEN 'Person' THEN 'connected' "
                "WHEN 'Message' THEN 'owned' ELSE 'observed' END"
            )

        if "retention_parent_id" in columns:
            retention_parent = "retention_parent_id"
        else:
            retention_parent = (
                "CASE WHEN entity_type = 'Message' THEN "
                "(SELECT target_entity_id FROM edges "
                "WHERE source_entity_id = entities.id AND edge_type = 'posted_in' LIMIT 1) "
                "ELSE NULL END"
            )

        observed = "NULL"
        if "observed_at" in columns and "cumulative_dwell_ms" in columns:
            observed = (
                "CASE WHEN entity_type IN ('Channel', 'Document', 'Email', 'Folder', 'Spreadsheet') "
                "AND cumulative_dwell_ms > 0 THEN observed_at ELSE NULL END"
            )
        dwell = "cumulative_dwell_ms" if "cumulative_dwell_ms" in columns else "0"
        bookmarked = "bookmarked" if "bookmarked" in columns else "0"
        await conn.execute("PRAGMA foreign_keys=OFF")
        try:
            await conn.execute("BEGIN")
            await conn.execute(
                """
                CREATE TABLE entities_new (
                    id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    platform_entity_id TEXT NOT NULL,
                    title TEXT,
                    content TEXT,
                    content_embedding BLOB,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    source_created_at TEXT,
                    source_updated_at TEXT,
                    synced_at TEXT,
                    observed_at TEXT,
                    retention_policy TEXT NOT NULL DEFAULT 'observed'
                        CHECK (retention_policy IN ('observed', 'owned', 'connected')),
                    retention_parent_id TEXT REFERENCES entities_new(id) ON DELETE CASCADE,
                    cumulative_dwell_ms INTEGER NOT NULL DEFAULT 0,
                    bookmarked INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (platform, platform_entity_id)
                )
                """
            )
            await conn.execute(
                f"""
                INSERT INTO entities_new
                    (id, entity_type, platform, platform_entity_id, title, content,
                     content_embedding, metadata, created_at, updated_at,
                     source_created_at, source_updated_at, synced_at, observed_at,
                     retention_policy, retention_parent_id, cumulative_dwell_ms, bookmarked)
                SELECT id, entity_type, platform, platform_entity_id, title, content,
                       content_embedding, metadata, {local_created}, {local_updated},
                       {source_created}, {source_updated}, synced_at, {observed},
                       {retention_policy}, {retention_parent}, {dwell}, {bookmarked}
                FROM entities
                """,
            )
            await conn.execute("DROP TABLE entities")
            await conn.execute("ALTER TABLE entities_new RENAME TO entities")
            await conn.execute("COMMIT")
        except Exception:
            await conn.execute("ROLLBACK")
            raise
        finally:
            await conn.execute("PRAGMA foreign_keys=ON")

    async def _fetchall(self, sql: str, params: list[Any] | None = None) -> list[Any]:
        conn = self._read_conn_or_raise()
        with timed("sqlite.fetchall"):
            cursor = await conn.execute(sql, params or [])
            return list(await cursor.fetchall())

    async def _fetchone(self, sql: str, params: list[Any] | None = None) -> Any:
        conn = self._read_conn_or_raise()
        with timed("sqlite.fetchone"):
            cursor = await conn.execute(sql, params or [])
            return await cursor.fetchone()

    async def _fetchval(self, sql: str, params: list[Any] | None = None) -> Any:
        row = await self._fetchone(sql, params)
        return row[0] if row else None

    async def _execute(self, sql: str, params: list[Any] | None = None) -> None:
        conn = self._conn_or_raise()
        with timed("sqlite.execute"):
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
            with timed(
                "sqlite.upsert_batch",
                entities=len(batch.entities),
                persons=len(batch.persons),
                edges=len(batch.edges),
            ):
                await conn.execute("BEGIN")
                try:
                    person_id_map = await self._upsert_persons(
                        conn, batch.persons, person_embeddings
                    )
                    entity_id_map = await self._upsert_entities(
                        conn, batch.entities, entity_embeddings
                    )
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
                existing_cursor = await conn.execute(
                    "SELECT title, content, content_embedding, metadata, updated_at FROM entities WHERE id = ?",
                    [existing_id],
                )
                existing_row = await existing_cursor.fetchone()
                if existing_row is None:
                    raise RuntimeError(f"Person entity {existing_id!r} disappeared during upsert")
                existing_title = str(existing_row[0]) if existing_row and existing_row[0] else ""
                existing_content = str(existing_row[1]) if existing_row and existing_row[1] else ""
                fts_title = p.display_name if p.display_name is not None else existing_title
                fts_content = (
                    p.canonical_email if p.canonical_email is not None else existing_content
                )
                rewrite_fts = fts_title != existing_title or fts_content != existing_content
                existing_metadata = json.loads(existing_row[3] or "{}") if existing_row else {}
                merged_metadata = {**existing_metadata, **meta}
                new_title = p.display_name if p.display_name is not None else existing_row[0]
                new_content = p.canonical_email if p.canonical_email is not None else existing_row[1]
                new_embedding = emb_blob if emb_blob is not None else existing_row[2]
                changed = (
                    new_title != existing_row[0]
                    or new_content != existing_row[1]
                    or new_embedding != existing_row[2]
                    or merged_metadata != existing_metadata
                )
                await conn.execute(
                    """
                    UPDATE entities
                    SET title = COALESCE(?, title),
                        content = COALESCE(?, content),
                        content_embedding = COALESCE(?, content_embedding),
                        metadata = json_patch(metadata, ?),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    [
                        p.display_name,
                        p.canonical_email,
                        emb_blob,
                        json.dumps(meta),
                        now if changed else existing_row[4],
                        existing_id,
                    ],
                )
                entity_id = existing_id
            else:
                cursor = await conn.execute(
                    """
                    INSERT INTO entities
                        (id, entity_type, platform, platform_entity_id, title, content,
                         content_embedding, metadata, retention_policy)
                    VALUES (?, 'Person', 'canonical', ?, ?, ?, ?, ?, 'connected')
                    RETURNING id
                    """,
                    [
                        _new_id(),
                        canonical_key,
                        p.display_name,
                        p.canonical_email,
                        emb_blob,
                        json.dumps(meta),
                    ],
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError("Failed to upsert person entity")
                entity_id = str(row[0])
                fts_title = p.display_name or ""
                fts_content = p.canonical_email or ""
                rewrite_fts = bool(fts_title or fts_content)

            if rewrite_fts:
                if existing_id is not None:
                    await conn.execute("DELETE FROM entities_fts WHERE id = ?", [entity_id])
                await conn.execute(
                    "INSERT INTO entities_fts (id, title, content) VALUES (?, ?, ?)",
                    [entity_id, fts_title, fts_content],
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
        # FTS maintenance is independent of edge resolution. Deferring it avoids
        # two SQLite round trips for every entity in a connector-sized batch.
        fts_delete_ids: list[str] = []
        fts_entries: dict[str, tuple[str, str]] = {}
        now = _now()
        for e in entities:
            parent_id: str | None = None
            if e.retention_policy == "owned":
                parent_ref = e.retention_parent_platform_entity_id
                if not parent_ref:
                    raise ValueError(
                        f"Owned entity {e.platform}:{e.platform_entity_id} has no retention parent"
                    )
                parent_id = id_map.get(parent_ref)
                if parent_id is None:
                    parent_id = await self._resolve_existing_entity_id(conn, e.platform, parent_ref)
                if parent_id is None:
                    raise ValueError(
                        f"Retention parent {e.platform}:{parent_ref} is not available"
                    )
            elif e.retention_parent_platform_entity_id is not None:
                raise ValueError(
                    f"Entity {e.platform}:{e.platform_entity_id} has a parent but is not owned"
                )

            if e.is_stub:
                cursor = await conn.execute(
                    """
                    INSERT INTO entities
                        (id, entity_type, platform, platform_entity_id, title, metadata,
                         retention_policy, retention_parent_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (platform, platform_entity_id) DO UPDATE SET
                        entity_type = entities.entity_type
                    RETURNING id
                    """,
                    [
                        _new_id(),
                        e.entity_type,
                        e.platform,
                        e.platform_entity_id,
                        e.title,
                        json.dumps(dict(e.metadata)),
                        e.retention_policy,
                        parent_id,
                    ],
                )
            else:
                existing_cursor = await conn.execute(
                    """
                    SELECT id, entity_type, title, content, content_embedding, metadata,
                           updated_at, source_created_at, source_updated_at,
                           retention_policy, retention_parent_id
                    FROM entities
                    WHERE platform = ? AND platform_entity_id = ?
                    """,
                    [e.platform, e.platform_entity_id],
                )
                existing_row = await existing_cursor.fetchone()
                existing_title = str(existing_row["title"]) if existing_row and existing_row["title"] else ""
                existing_content = str(existing_row["content"]) if existing_row and existing_row["content"] else ""
                fts_title = e.title if e.title is not None else existing_title
                fts_content = e.content if e.content is not None else existing_content
                rewrite_fts = (
                    existing_row is None
                    or fts_title != existing_title
                    or fts_content != existing_content
                )
                embedding = embeddings.get(e.platform_entity_id)
                emb_blob = pack_embedding(embedding) if embedding else None
                source_created = (
                    e.source_created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if e.source_created_at
                    else None
                )
                source_updated = (
                    e.source_updated_at.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if e.source_updated_at
                    else None
                )
                metadata = dict(e.metadata)
                if existing_row is None:
                    changed = True
                    local_updated = now
                else:
                    target_type = (
                        e.entity_type
                        if existing_row["entity_type"] == "Document"
                        else existing_row["entity_type"]
                    )
                    target_title = e.title if e.title is not None else existing_row["title"]
                    target_content = e.content if e.content is not None else existing_row["content"]
                    target_embedding = (
                        emb_blob if emb_blob is not None else existing_row["content_embedding"]
                    )
                    target_source_created = (
                        source_created
                        if source_created is not None
                        else existing_row["source_created_at"]
                    )
                    target_source_updated = (
                        source_updated
                        if source_updated is not None
                        else existing_row["source_updated_at"]
                    )
                    changed = (
                        target_type != existing_row["entity_type"]
                        or target_title != existing_row["title"]
                        or target_content != existing_row["content"]
                        or target_embedding != existing_row["content_embedding"]
                        or metadata != json.loads(existing_row["metadata"] or "{}")
                        or target_source_created != existing_row["source_created_at"]
                        or target_source_updated != existing_row["source_updated_at"]
                        or e.retention_policy != existing_row["retention_policy"]
                        or parent_id != existing_row["retention_parent_id"]
                    )
                    local_updated = now if changed else str(existing_row["updated_at"])
                cursor = await conn.execute(
                    """
                    INSERT INTO entities
                        (id, entity_type, platform, platform_entity_id, title, content,
                         content_embedding, metadata, source_created_at, source_updated_at,
                         synced_at, retention_policy, retention_parent_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (platform, platform_entity_id) DO UPDATE SET
                        entity_type       = CASE WHEN entities.entity_type = 'Document' THEN EXCLUDED.entity_type ELSE entities.entity_type END,
                        title             = COALESCE(EXCLUDED.title, entities.title),
                        content           = COALESCE(EXCLUDED.content, entities.content),
                        content_embedding = COALESCE(EXCLUDED.content_embedding, entities.content_embedding),
                        metadata          = EXCLUDED.metadata,
                        source_created_at = COALESCE(EXCLUDED.source_created_at, entities.source_created_at),
                        source_updated_at = COALESCE(EXCLUDED.source_updated_at, entities.source_updated_at),
                        synced_at         = EXCLUDED.synced_at,
                        retention_policy  = EXCLUDED.retention_policy,
                        retention_parent_id = EXCLUDED.retention_parent_id,
                        updated_at        = ?
                    RETURNING id
                    """,
                    [
                        _new_id(),
                        e.entity_type,
                        e.platform,
                        e.platform_entity_id,
                        e.title,
                        e.content,
                        emb_blob,
                        json.dumps(metadata),
                        source_created,
                        source_updated,
                        now,
                        e.retention_policy,
                        parent_id,
                        local_updated,
                    ],
                )

                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError(
                        f"Failed to upsert entity {e.platform}:{e.platform_entity_id}"
                    )
                entity_id: str = row[0]
                if rewrite_fts:
                    if existing_row is not None:
                        fts_delete_ids.append(entity_id)
                    if fts_title or fts_content:
                        fts_entries[entity_id] = (fts_title, fts_content)
                id_map[e.platform_entity_id] = entity_id
                continue

            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError(
                    f"Failed to upsert stub entity {e.platform}:{e.platform_entity_id}"
                )
            id_map[e.platform_entity_id] = row[0]

        for start in range(0, len(fts_delete_ids), _FTS_DELETE_CHUNK_SIZE):
            ids = fts_delete_ids[start : start + _FTS_DELETE_CHUNK_SIZE]
            placeholders = ",".join("?" * len(ids))
            await conn.execute(f"DELETE FROM entities_fts WHERE id IN ({placeholders})", ids)
        inserts = [
            [entity_id, title, content]
            for entity_id, entry in fts_entries.items()
            for title, content in [entry]
        ]
        if inserts:
            await conn.executemany(
                "INSERT INTO entities_fts (id, title, content) VALUES (?, ?, ?)", inserts
            )
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
                [
                    _new_id(),
                    edge.edge_type,
                    source_id,
                    target_id,
                    edge.platform,
                    json.dumps(dict(edge.properties)),
                    now,
                ],
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
                           title, content, metadata, observed_at
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
                primary_metadata = json.loads(primary["metadata"] or "{}")
                merged_people: list[dict[str, str]] = []
                merged_person_ids: set[str] = set()
                _append_merged_people(
                    primary_metadata,
                    merged_people,
                    merged_person_ids,
                )
                for eid in duplicate_ids:
                    duplicate = by_id[eid]
                    duplicate_metadata = json.loads(duplicate["metadata"] or "{}")
                    _append_merged_people(
                        duplicate_metadata,
                        merged_people,
                        merged_person_ids,
                    )

                    merged_people.append(
                        {
                            "id": eid,
                            "title": str(duplicate["title"] or duplicate["platform_entity_id"]),
                            "platform_entity_id": str(duplicate["platform_entity_id"]),
                        }
                    )
                    merged_person_ids.add(eid)

                merged_metadata: dict[str, Any] = {}
                for eid in duplicate_ids:
                    merged_metadata.update(json.loads(by_id[eid]["metadata"] or "{}"))
                merged_metadata.update(primary_metadata)
                merged_metadata["merged_people"] = merged_people

                title = primary["title"] or next(
                    (by_id[eid]["title"] for eid in duplicate_ids if by_id[eid]["title"]),
                    None,
                )
                content = primary["content"] or next(
                    (by_id[eid]["content"] for eid in duplicate_ids if by_id[eid]["content"]),
                    None,
                )
                await conn.execute(
                    """
                    UPDATE entities
                    SET title = ?, content = ?, metadata = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    [title, content, json.dumps(merged_metadata), _now(), primary_entity_id],
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

    async def set_entity_bookmarked(
        self,
        entity_id: str,
        bookmarked: bool,
    ) -> EntityResult:
        now = _now()
        cursor = await self._conn_or_raise().execute(
            """
            UPDATE entities
            SET bookmarked = ?, updated_at = ?
            WHERE id = ?
            RETURNING id, entity_type, platform, platform_entity_id,
                      title, content, metadata, created_at, updated_at,
                      source_created_at, source_updated_at, synced_at, observed_at,
                      retention_policy, retention_parent_id,
                      cumulative_dwell_ms, bookmarked
            """,
            [1 if bookmarked else 0, now, entity_id],
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError(f"Entity {entity_id!r} not found")
        return _row_to_entity(row)

    async def delete_entity(self, entity_id: str) -> EntityResult:
        """Delete one entity by internal ID. Edges cascade; FTS rows are removed explicitly."""
        assert self._write_lock is not None
        async with self._write_lock:
            conn = self._conn_or_raise()
            await conn.execute("BEGIN")
            try:
                await conn.execute(
                    """
                    UPDATE entities
                    SET retention_parent_id = NULL, updated_at = ?
                    WHERE retention_parent_id = ? AND bookmarked = 1
                    """,
                    [_now(), entity_id],
                )
                cursor = await conn.execute(
                    """
                    DELETE FROM entities
                    WHERE id = ?
                    RETURNING id, entity_type, platform, platform_entity_id,
                              title, content, metadata, created_at, updated_at,
                              source_created_at, source_updated_at, synced_at, observed_at,
                              retention_policy, retention_parent_id,
                              cumulative_dwell_ms, bookmarked
                    """,
                    [entity_id],
                )
                row = await cursor.fetchone()
                if row is None:
                    raise ValueError(f"Entity {entity_id!r} not found")
                await conn.execute(
                    "DELETE FROM entities_fts WHERE id NOT IN (SELECT id FROM entities)"
                )
                await conn.execute("COMMIT")
            except Exception:
                await conn.execute("ROLLBACK")
                raise
        return _row_to_entity(row)

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
        conn = self._read_conn_or_raise()

        with timed("sqlite.search_entities", limit=limit, platform=platform):
            initial_candidate_limit = limit * 2
            max_candidate_limit = limit * 5

            # BM25 via FTS5
            fts_ids: list[tuple[str, int]] = []
            with timed("sqlite.search.fts", limit=initial_candidate_limit, platform=platform):
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
                        [_fts5_query(query_text), *fts_extra_params, initial_candidate_limit],
                    )
                    rows = await cursor.fetchall()
                    fts_ids = [(row[0], i + 1) for i, row in enumerate(rows)]
                except Exception:
                    pass

            # Vector search is the expensive leg. A saturated initial FTS
            # window already has enough lexical candidates for the requested
            # result count, so avoid the O(n) vector scan in that common case.
            # Sparse FTS queries use the larger window to preserve the existing
            # hybrid-search recall.
            if len(fts_ids) >= initial_candidate_limit:
                vec_ids: list[tuple[str, int]] = []
                logger.debug(
                    "search skipped vector scan because FTS returned %d candidates",
                    len(fts_ids),
                )
            else:
                vec_ids = await vector_ranked(
                    conn,
                    query_vec,
                    entity_types,
                    limit,
                    self._vector_mode,
                    self._vec_loaded,
                    platform=platform,
                    candidate_limit=max_candidate_limit,
                )

            # RRF fusion (k=60, fulltext weight=2x)
            # Rule: if BM25 found anything, include only results that BM25 also found.
            with timed("sqlite.search.fusion", limit=limit):
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
            with timed("sqlite.search.hydrate", count=len(id_list)):
                cursor = await conn.execute(
                    f"""
                    SELECT id, entity_type, platform, platform_entity_id,
                           title, content, metadata, created_at, updated_at,
                           source_created_at, source_updated_at, synced_at, observed_at,
                           retention_policy, retention_parent_id,
                           cumulative_dwell_ms, bookmarked
                    FROM entities WHERE id IN ({placeholders})
                    """,
                    id_list,
                )
                rows = await cursor.fetchall()
                results: list[dict[str, Any]] = []
                for row in rows:
                    r = _row_to_entity(row)
                    base_score = score_map.get(r["id"], 0.0)
                    dwell_ms = r.get("cumulative_dwell_ms", 0)
                    dwell_boost = 0.1 * math.log10(1 + (dwell_ms / 1000.0))
                    r["score"] = base_score + dwell_boost

                    if (r["score"] or 0) >= min_score:
                        results.append(r)

                def _score(result: dict[str, Any]) -> float:
                    raw_score = result.get("score")
                    return float(raw_score) if isinstance(raw_score, int | float) else 0.0

                results.sort(key=_score, reverse=True)
                return results

    async def get_entity_by_id(self, entity_id: str) -> EntityResult | None:
        row = await self._fetchone(
            """
            SELECT id, entity_type, platform, platform_entity_id,
                   title, content, metadata, created_at, updated_at,
                   source_created_at, source_updated_at, synced_at, observed_at,
                   retention_policy, retention_parent_id,
                   cumulative_dwell_ms, bookmarked
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
                   title, content, metadata, created_at, updated_at,
                   source_created_at, source_updated_at, synced_at, observed_at,
                   retention_policy, retention_parent_id,
                   cumulative_dwell_ms, bookmarked
            FROM entities WHERE id IN ({placeholders})
            """,
            entity_ids,
        )
        return [_row_to_entity(r) for r in rows]

    async def get_entities_by_id_prefix(self, prefix: str) -> list[EntityResult]:
        rows = await self._fetchall(
            """
            SELECT id, entity_type, platform, platform_entity_id,
                   title, content, metadata, created_at, updated_at,
                   source_created_at, source_updated_at, synced_at, observed_at,
                   retention_policy, retention_parent_id,
                   cumulative_dwell_ms, bookmarked
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
                   title, content, metadata, created_at, updated_at,
                   source_created_at, source_updated_at, synced_at, observed_at,
                   retention_policy, retention_parent_id,
                   cumulative_dwell_ms, bookmarked
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
                   title, content, metadata, created_at, updated_at,
                   source_created_at, source_updated_at, synced_at, observed_at,
                   retention_policy, retention_parent_id,
                   cumulative_dwell_ms, bookmarked
            FROM entities
            {where}
            ORDER BY observed_at DESC
            LIMIT ?
            """,
            params,
        )
        return [_row_to_entity(row) for row in rows]

    async def list_entities_page(
        self,
        entity_types: list[str] | None,
        platform: str | None,
        since: datetime | None,
        limit: int,
        offset: int,
        order_by: str | None,
        order_dir: str,
    ) -> tuple[list[EntityResult], int]:
        order_by_sql = (
            _LIST_PAGE_ORDER_BY.get(order_by, "observed_at") if order_by is not None else None
        )
        if order_dir.upper() not in {"ASC", "DESC"}:
            order_dir = "DESC"
        order_clause = (
            f"ORDER BY {order_by_sql} {order_dir}, id ASC" if order_by_sql is not None else ""
        )

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

        count_row = await self._fetchone(f"SELECT COUNT(*) AS count FROM entities {where}", params)
        total = int(count_row["count"]) if count_row else 0
        rows = await self._fetchall(
            f"""
            SELECT id, entity_type, platform, platform_entity_id,
                   title, content, metadata, created_at, updated_at,
                   source_created_at, source_updated_at, synced_at, observed_at,
                   retention_policy, retention_parent_id,
                   cumulative_dwell_ms, bookmarked
            FROM entities
            {where}
            {order_clause}
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        )
        return [_row_to_entity(row) for row in rows], total

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
            order_by = "observed_at"

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
        with timed(
            "sqlite.query_by_filter", entity_type=entity_type, order_by=order_by, limit=limit
        ):
            rows = await self._fetchall(
                f"""
                SELECT e.id, e.entity_type, e.platform, e.platform_entity_id,
                       e.title, e.content, e.metadata, e.created_at, e.updated_at,
                       e.source_created_at, e.source_updated_at,
                       e.synced_at, e.observed_at,
                       e.retention_policy, e.retention_parent_id,
                       e.cumulative_dwell_ms, e.bookmarked
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
        conn = self._read_conn_or_raise()
        visited: set[str] = set()
        frontier: list[str] = [entity_id]
        all_nodes: list[EntityResult] = []
        all_edges: list[EdgeResult] = []
        seen_edge_ids: set[str] = set()

        for _ in range(max_depth):
            if not frontier:
                break
            placeholders = ",".join("?" * len(frontier))
            cursor = await conn.execute(
                f"""
                SELECT id, entity_type, platform, platform_entity_id,
                       title, content, metadata, created_at, updated_at,
                       source_created_at, source_updated_at, synced_at, observed_at,
                       retention_policy, retention_parent_id,
                       cumulative_dwell_ms, bookmarked
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
                edge_id = str(row["id"])
                if edge_id not in seen_edge_ids:
                    seen_edge_ids.add(edge_id)
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
                       title, content, metadata, created_at, updated_at,
                       source_created_at, source_updated_at, synced_at, observed_at,
                       retention_policy, retention_parent_id,
                       cumulative_dwell_ms, bookmarked
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
            INSERT INTO entities (id, entity_type, platform, platform_entity_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (platform, platform_entity_id) DO UPDATE SET
                entity_type = entities.entity_type
            RETURNING id
            """,
            [_new_id(), entity_type, platform, platform_entity_id],
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError(f"Failed to upsert stub entity {platform}:{platform_entity_id}")
        return row[0]

    async def insert_references_edge(self, source_id: str, target_id: str) -> None:
        await self._conn_or_raise().execute(
            """
            INSERT INTO edges (id, edge_type, source_entity_id, target_entity_id, platform, properties)
            VALUES (?, 'references', ?, ?, 'cross', '{}')
            ON CONFLICT (edge_type, source_entity_id, target_entity_id) DO NOTHING
            """,
            [_new_id(), source_id, target_id],
        )

    # --- Expiration ---

    async def expire_entities(self, retention_days: float, dry_run: bool = False) -> int:
        # SQLite doesn't have interval arithmetic; compute cutoff in Python
        from datetime import timedelta

        cutoff_dt = datetime.now(UTC) - timedelta(days=retention_days)
        cutoff = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        assert self._write_lock is not None
        async with self._write_lock:
            conn = self._conn_or_raise()
            await conn.execute("BEGIN")
            try:
                before_cursor = await conn.execute("SELECT count(*) FROM entities")
                before_row = await before_cursor.fetchone()
                before_count = int(before_row[0]) if before_row else 0
                expired_sql = """
                    retention_policy = 'observed'
                    AND bookmarked = 0
                    AND COALESCE(observed_at, created_at) <= ?
                """

                # A bookmarked owned child survives parent collection as a detached entity.
                await conn.execute(
                    f"""
                    UPDATE entities
                    SET retention_parent_id = NULL, updated_at = ?
                    WHERE bookmarked = 1
                      AND retention_parent_id IN (
                          SELECT id FROM entities WHERE {expired_sql}
                      )
                    """,
                    [_now(), cutoff],
                )
                await conn.execute(f"DELETE FROM entities WHERE {expired_sql}", [cutoff])
                await conn.execute(
                    """
                    DELETE FROM entities
                    WHERE retention_policy = 'owned'
                      AND retention_parent_id IS NULL
                      AND bookmarked = 0
                    """
                )
                await conn.execute(
                    """
                    DELETE FROM entities
                    WHERE retention_policy = 'connected'
                      AND bookmarked = 0
                      AND NOT EXISTS (
                          SELECT 1 FROM edges
                          WHERE source_entity_id = entities.id OR target_entity_id = entities.id
                      )
                    """
                )
                await conn.execute(
                    "DELETE FROM entities_fts WHERE id NOT IN (SELECT id FROM entities)"
                )
                after_cursor = await conn.execute("SELECT count(*) FROM entities")
                after_row = await after_cursor.fetchone()
                after_count = int(after_row[0]) if after_row else 0
                if dry_run:
                    await conn.execute("ROLLBACK")
                else:
                    await conn.execute("COMMIT")
            except Exception:
                await conn.execute("ROLLBACK")
                raise
        return before_count - after_count

    # --- Observations ---

    # --- Sync state ---

    async def load_cursor(self, source: str) -> dict[str, Any]:
        val = await self._fetchval("SELECT cursor FROM sync_state WHERE source = ?", [source])
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
        now = _now()
        await self._execute(
            """
            UPDATE entities
            SET cumulative_dwell_ms = cumulative_dwell_ms + ?, updated_at = ?
            WHERE platform = ? AND platform_entity_id = ?
            """,
            [dwell_ms, now, platform, platform_entity_id],
        )

    async def record_observation(
        self, platform: str, platform_entity_id: str, dwell_ms: int
    ) -> None:
        now = _now()
        await self._execute(
            """
            UPDATE entities
            SET cumulative_dwell_ms = cumulative_dwell_ms + ?,
                observed_at = ?,
                updated_at = CASE WHEN ? > 0 THEN ? ELSE updated_at END
            WHERE platform = ? AND platform_entity_id = ?
              AND retention_policy = 'observed'
            """,
            [dwell_ms, now, dwell_ms, now, platform, platform_entity_id],
        )

    async def record_observation_once(
        self,
        platform: str,
        platform_entity_id: str,
        observation_id: str,
        url: str,
        dwell_ms: int,
    ) -> bool:
        assert self._write_lock is not None
        async with self._write_lock:
            conn = self._conn_or_raise()
            now = _now()
            await conn.execute("BEGIN")
            try:
                cursor = await conn.execute(
                    """
                    INSERT INTO observations (
                        id, event_type, url, timestamp, evaluated
                    ) VALUES (?, 'dwell_threshold', ?, ?, 1)
                    ON CONFLICT(id) DO NOTHING
                    RETURNING id
                    """,
                    [observation_id, url, now],
                )
                inserted = await cursor.fetchone()
                if inserted is not None:
                    await conn.execute(
                        """
                        UPDATE entities
                        SET cumulative_dwell_ms = cumulative_dwell_ms + ?,
                            observed_at = ?,
                            updated_at = CASE WHEN ? > 0 THEN ? ELSE updated_at END
                        WHERE platform = ? AND platform_entity_id = ?
                          AND retention_policy = 'observed'
                        """,
                        [dwell_ms, now, dwell_ms, now, platform, platform_entity_id],
                    )
                await conn.execute("COMMIT")
                return inserted is not None
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def get_last_synced_at(self, platform: str, platform_entity_id: str) -> datetime | None:
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

    async def get_platforms_last_synced_at(
        self,
        platforms: list[str],
    ) -> dict[str, datetime | None]:
        if not platforms:
            return {}
        placeholders = ",".join("?" for _ in platforms)
        rows = await self._fetchall(
            f"""
            SELECT platform, max(synced_at) AS last_synced_at
            FROM entities
            WHERE platform IN ({placeholders})
            GROUP BY platform
            """,
            platforms,
        )
        result: dict[str, datetime | None] = dict.fromkeys(platforms, None)
        for row in rows:
            val = row["last_synced_at"]
            result[row["platform"]] = datetime.fromisoformat(val) if val else None
        return result

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
        "source_created_at": row["source_created_at"] if "source_created_at" in keys else None,
        "source_updated_at": row["source_updated_at"] if "source_updated_at" in keys else None,
        "synced_at": row["synced_at"] if "synced_at" in keys else None,
        "observed_at": row["observed_at"] if "observed_at" in keys else None,
        "retention_policy": row["retention_policy"] if "retention_policy" in keys else "observed",
        "retention_parent_id": row["retention_parent_id"] if "retention_parent_id" in keys else None,
        "cumulative_dwell_ms": row["cumulative_dwell_ms"] if "cumulative_dwell_ms" in keys else 0,
        "bookmarked": bool(row["bookmarked"]) if "bookmarked" in keys else False,
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
