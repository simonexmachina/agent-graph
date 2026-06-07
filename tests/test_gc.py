"""Tests for backend-level garbage collection behavior."""

# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import sqlite3
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agentgraph.backends.sqlite.backend import SQLiteBackend


@pytest.fixture()
async def sqlite_backend() -> AsyncGenerator[SQLiteBackend, None]:
    backend = SQLiteBackend(":memory:")
    await backend.initialize()
    yield backend
    await backend.close()


async def test_sqlite_gc_removes_stale_entities_edges_and_fts(
    sqlite_backend: SQLiteBackend,
) -> None:
    conn = sqlite_backend._conn_or_raise()
    stale_id = "stale-entity"
    fresh_id = "fresh-entity"
    stale_time = (datetime.now(UTC) - timedelta(days=100)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh_time = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    await conn.execute(
        """
        INSERT INTO entities (id, entity_type, platform, platform_entity_id, title, last_accessed)
        VALUES (?, 'Document', 'gdrive', 'old-file', 'Old file', ?)
        """,
        [stale_id, stale_time],
    )
    await conn.execute(
        """
        INSERT INTO entities (id, entity_type, platform, platform_entity_id, title, last_accessed)
        VALUES (?, 'Document', 'gdrive', 'new-file', 'New file', ?)
        """,
        [fresh_id, fresh_time],
    )
    await conn.execute(
        "INSERT INTO entities_fts (id, title, content) VALUES (?, ?, ?)",
        [stale_id, "Old file", "stale content"],
    )
    await conn.execute(
        """
        INSERT INTO edges (id, edge_type, source_entity_id, target_entity_id, platform)
        VALUES (?, 'references', ?, ?, 'cross')
        """,
        ["edge-1", stale_id, fresh_id],
    )

    deleted = await sqlite_backend.gc_entities(90)
    assert deleted == 1

    stale_count = await sqlite_backend._fetchval(
        "SELECT count(*) FROM entities WHERE platform_entity_id = ?",
        ["old-file"],
    )
    fresh_count = await sqlite_backend._fetchval(
        "SELECT count(*) FROM entities WHERE platform_entity_id = ?",
        ["new-file"],
    )
    edge_count = await sqlite_backend._fetchval("SELECT count(*) FROM edges")
    fts_count = await sqlite_backend._fetchval(
        "SELECT count(*) FROM entities_fts WHERE id = ?",
        [stale_id],
    )

    assert stale_count == 0
    assert fresh_count == 1
    assert edge_count == 0
    assert fts_count == 0


async def test_sqlite_gc_keeps_bookmarked_stale_entities(
    sqlite_backend: SQLiteBackend,
) -> None:
    conn = sqlite_backend._conn_or_raise()
    stale_id = "bookmarked-stale-entity"
    stale_time = (datetime.now(UTC) - timedelta(days=100)).strftime("%Y-%m-%dT%H:%M:%SZ")

    await conn.execute(
        """
        INSERT INTO entities (
            id, entity_type, platform, platform_entity_id, title, last_accessed, bookmarked
        )
        VALUES (?, 'Document', 'gdrive', 'old-file', 'Old file', ?, 1)
        """,
        [stale_id, stale_time],
    )
    await conn.execute(
        "INSERT INTO entities_fts (id, title, content) VALUES (?, ?, ?)",
        [stale_id, "Old file", "stale content"],
    )

    deleted = await sqlite_backend.gc_entities(90)
    assert deleted == 0

    entity = await sqlite_backend.get_entity_by_id(stale_id)
    assert entity is not None
    assert entity["bookmarked"] is True
    fts_count = await sqlite_backend._fetchval(
        "SELECT count(*) FROM entities_fts WHERE id = ?",
        [stale_id],
    )
    assert fts_count == 1


async def test_sqlite_set_entity_bookmarked_returns_updated_entity(
    sqlite_backend: SQLiteBackend,
) -> None:
    conn = sqlite_backend._conn_or_raise()
    entity_id = "bookmark-target"
    await conn.execute(
        """
        INSERT INTO entities (id, entity_type, platform, platform_entity_id, title)
        VALUES (?, 'Document', 'gdrive', 'file', 'File')
        """,
        [entity_id],
    )

    entity = await sqlite_backend.set_entity_bookmarked(entity_id, True)

    assert entity["id"] == entity_id
    assert entity["bookmarked"] is True


async def test_sqlite_delete_entity_removes_entity_edges_and_fts(
    sqlite_backend: SQLiteBackend,
) -> None:
    conn = sqlite_backend._conn_or_raise()
    entity_id = "delete-target"
    other_id = "delete-neighbour"
    await conn.execute(
        """
        INSERT INTO entities (id, entity_type, platform, platform_entity_id, title)
        VALUES (?, 'Document', 'gdrive', 'file', 'File')
        """,
        [entity_id],
    )
    await conn.execute(
        """
        INSERT INTO entities (id, entity_type, platform, platform_entity_id, title)
        VALUES (?, 'Document', 'gdrive', 'other-file', 'Other file')
        """,
        [other_id],
    )
    await conn.execute(
        "INSERT INTO entities_fts (id, title, content) VALUES (?, ?, ?)",
        [entity_id, "File", "content"],
    )
    await conn.execute(
        """
        INSERT INTO edges (id, edge_type, source_entity_id, target_entity_id, platform)
        VALUES (?, 'references', ?, ?, 'cross')
        """,
        ["delete-edge", entity_id, other_id],
    )

    deleted = await sqlite_backend.delete_entity(entity_id)

    entity_count = await sqlite_backend._fetchval(
        "SELECT count(*) FROM entities WHERE id = ?",
        [entity_id],
    )
    other_count = await sqlite_backend._fetchval(
        "SELECT count(*) FROM entities WHERE id = ?",
        [other_id],
    )
    edge_count = await sqlite_backend._fetchval("SELECT count(*) FROM edges")
    fts_count = await sqlite_backend._fetchval(
        "SELECT count(*) FROM entities_fts WHERE id = ?",
        [entity_id],
    )

    assert deleted["id"] == entity_id
    assert entity_count == 0
    assert other_count == 1
    assert edge_count == 0
    assert fts_count == 0


async def test_sqlite_migration_adds_bookmarked_before_index(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE entities (
                id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                platform TEXT NOT NULL,
                platform_entity_id TEXT NOT NULL,
                title TEXT,
                content TEXT,
                content_embedding BLOB,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT,
                updated_at TEXT,
                synced_at TEXT,
                last_accessed TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                cumulative_dwell_ms INTEGER NOT NULL DEFAULT 0,
                UNIQUE (platform, platform_entity_id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    backend = SQLiteBackend(str(db_path))
    await backend.initialize()
    try:
        columns = await backend._fetchall("PRAGMA table_info(entities)")
        indexes = await backend._fetchall("PRAGMA index_list(entities)")
    finally:
        await backend.close()

    assert "bookmarked" in {row["name"] for row in columns}
    assert "idx_entities_bookmarked" in {row["name"] for row in indexes}
