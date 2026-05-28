"""Tests for the SQLite database schema."""

from __future__ import annotations

from collections.abc import AsyncGenerator

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
