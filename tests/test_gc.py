"""Tests for backend-level garbage collection behavior."""

# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

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
