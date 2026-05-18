"""Tests for backend-level garbage collection behavior."""

# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest

from agentgraph.backends.postgres.backend import PostgresBackend
from agentgraph.backends.sqlite.backend import SQLiteBackend
from agentgraph.config import get_settings


@pytest.fixture()
async def pg_backend() -> AsyncGenerator[PostgresBackend, None]:
    settings = get_settings()
    backend = PostgresBackend(settings.database_url)
    await backend.initialize()
    yield backend
    pool = backend._pool_or_raise()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM edges")
        await conn.execute("DELETE FROM entities")
    await backend.close()


@pytest.fixture()
async def sqlite_backend() -> AsyncGenerator[SQLiteBackend, None]:
    backend = SQLiteBackend(":memory:")
    await backend.initialize()
    yield backend
    await backend.close()


@pytest.mark.integration
async def test_postgres_gc_removes_stale_entities_and_cascades_edges(
    pg_backend: PostgresBackend,
) -> None:
    pool = pg_backend._pool_or_raise()
    async with pool.acquire() as conn:
        stale_id = await conn.fetchval(
            """
            INSERT INTO entities (entity_type, platform, platform_entity_id, last_accessed)
            VALUES ('Message', 'slack', 'old-msg-1', now() - INTERVAL '100 days')
            RETURNING id
            """
        )
        fresh_id = await conn.fetchval(
            """
            INSERT INTO entities (entity_type, platform, platform_entity_id, last_accessed)
            VALUES ('Message', 'slack', 'new-msg-1', now() - INTERVAL '1 day')
            RETURNING id
            """
        )
        await conn.execute(
            """
            INSERT INTO edges (edge_type, source_entity_id, target_entity_id, platform)
            VALUES ('references', $1, $2, 'cross')
            """,
            stale_id,
            fresh_id,
        )

    deleted = await pg_backend.gc_entities(90)
    assert deleted == 1

    async with pool.acquire() as conn:
        old_count = await conn.fetchval(
            "SELECT count(*) FROM entities WHERE platform_entity_id = 'old-msg-1'"
        )
        new_count = await conn.fetchval(
            "SELECT count(*) FROM entities WHERE platform_entity_id = 'new-msg-1'"
        )
        edge_count = await conn.fetchval("SELECT count(*) FROM edges")

    assert old_count == 0
    assert new_count == 1
    assert edge_count == 0


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
