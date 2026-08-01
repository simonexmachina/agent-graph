"""Tests for the SQLite database schema."""

from __future__ import annotations

# pyright: reportPrivateUsage=false
import sqlite3
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from agentgraph.backends.sqlite.backend import SQLiteBackend
from agentgraph.core.context import set_backend


@pytest.fixture()
async def sqlite_backend() -> AsyncGenerator[SQLiteBackend, None]:
    backend = SQLiteBackend(":memory:")
    await backend.initialize()
    set_backend(backend)
    yield backend
    await backend.close()


async def test_tables_exist(sqlite_backend: SQLiteBackend) -> None:
    rows = await sqlite_backend._fetchall(
        """
        SELECT name FROM sqlite_master
        WHERE type IN ('table', 'view')
        ORDER BY name
        """
    )
    names = {row["name"] for row in rows}
    assert {"entities", "edges", "observations", "sync_state", "entities_fts"} <= names
    assert "persons" not in names
    assert "platform_identities" not in names


async def test_insert_person_and_entity_and_edge(sqlite_backend: SQLiteBackend) -> None:
    conn = sqlite_backend._conn_or_raise()
    person_id = "person-1"
    entity_id = "entity-1"
    edge_id = "edge-1"

    await conn.execute(
        """
        INSERT INTO entities (id, entity_type, platform, platform_entity_id, title, content)
        VALUES (?, 'Person', 'canonical', 'test@example.com', 'Test User', 'test@example.com')
        ON CONFLICT (platform, platform_entity_id) DO UPDATE SET title = EXCLUDED.title
        """,
        [person_id],
    )
    await conn.execute(
        """
        INSERT INTO entities (id, entity_type, platform, platform_entity_id, title, content)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (platform, platform_entity_id) DO UPDATE SET title = EXCLUDED.title
        """,
        [entity_id, "Document", "gdocs", "test-doc-001", "Test Document", "Some content here"],
    )
    await conn.execute(
        """
        INSERT INTO edges (id, edge_type, source_entity_id, target_entity_id)
        VALUES (?, ?, ?, ?)
        """,
        [edge_id, "authored", person_id, entity_id],
    )

    await conn.execute("DELETE FROM entities WHERE id = ?", [entity_id])
    count = await sqlite_backend._fetchval("SELECT count(*) FROM edges WHERE id = ?", [edge_id])
    assert count == 0


async def test_get_platforms_last_synced_at_groups_platforms(sqlite_backend: SQLiteBackend) -> None:
    conn = sqlite_backend._conn_or_raise()
    await conn.executemany(
        """
        INSERT INTO entities (id, entity_type, platform, platform_entity_id, synced_at)
        VALUES (?, 'Document', ?, ?, ?)
        """,
        [
            ["entity-1", "rss", "feed-1", "2026-06-23T10:00:00+00:00"],
            ["entity-2", "rss", "feed-2", "2026-06-23T12:00:00+00:00"],
            ["entity-3", "gmail", "thread-1", "2026-06-22T09:00:00+00:00"],
        ],
    )

    result = await sqlite_backend.get_platforms_last_synced_at(["rss", "gmail", "slack"])

    rss_synced_at = result["rss"]
    gmail_synced_at = result["gmail"]
    assert rss_synced_at is not None
    assert gmail_synced_at is not None
    assert rss_synced_at.isoformat() == "2026-06-23T12:00:00+00:00"
    assert gmail_synced_at.isoformat() == "2026-06-22T09:00:00+00:00"
    assert result["slack"] is None


async def test_schema_has_platform_synced_at_index(sqlite_backend: SQLiteBackend) -> None:
    rows = await sqlite_backend._fetchall(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'index'
        """
    )
    names = {row["name"] for row in rows}
    assert "idx_entities_platform_synced_at" in names
    assert "idx_entities_type_last_accessed" in names
    assert "idx_entities_type_created_at" in names
    assert "idx_entities_type_updated_at" in names
    assert "idx_entities_platform_type_last_accessed" in names
    assert "idx_entities_last_accessed_id" in names


async def test_file_database_uses_separate_read_connection(tmp_path: Path) -> None:
    backend = SQLiteBackend(str(tmp_path / "graph.db"))
    await backend.initialize()
    try:
        assert backend._read_conn is not backend._conn
    finally:
        await backend.close()


async def test_existing_database_gets_cumulative_dwell_column(tmp_path: Path) -> None:
    db_path = tmp_path / "old-schema.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE entities (
            id                 TEXT PRIMARY KEY,
            entity_type        TEXT NOT NULL,
            platform           TEXT NOT NULL,
            platform_entity_id TEXT NOT NULL,
            title              TEXT,
            content            TEXT,
            content_embedding  BLOB,
            metadata           TEXT NOT NULL DEFAULT '{}',
            created_at         TEXT,
            updated_at         TEXT,
            synced_at          TEXT,
            last_accessed      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            UNIQUE (platform, platform_entity_id)
        );
        CREATE VIRTUAL TABLE entities_fts USING fts5(
            id      UNINDEXED,
            title,
            content,
            tokenize='porter ascii'
        );
        """
    )
    conn.execute(
        """
        INSERT INTO entities (id, entity_type, platform, platform_entity_id, title, content)
        VALUES (?, 'Document', 'gdocs', 'test-doc-001', 'Test Document', 'Some content')
        """,
        ["entity-1"],
    )
    conn.commit()
    conn.close()

    migrated = SQLiteBackend(str(db_path))
    await migrated.initialize()
    try:
        columns = await migrated._fetchall("PRAGMA table_info(entities)")
        assert "cumulative_dwell_ms" in {row["name"] for row in columns}

        entity = await migrated.get_entity_by_platform("gdocs", "test-doc-001")
        assert entity is not None
        assert entity["cumulative_dwell_ms"] == 0

        await migrated.increment_dwell_time("gdocs", "test-doc-001", 1234)
        updated = await migrated.get_entity_by_platform("gdocs", "test-doc-001")
        assert updated is not None
        assert updated["cumulative_dwell_ms"] == 1234
    finally:
        await migrated.close()
