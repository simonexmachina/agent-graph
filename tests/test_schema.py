"""Integration tests for the database schema."""

from __future__ import annotations

import pytest

from agentgraph.backends.postgres.backend import PostgresBackend
from agentgraph.config import get_settings
from agentgraph.core.context import set_backend


@pytest.fixture(autouse=True)
async def pg_backend():
    """Set up and tear down the PostgresBackend for each test."""
    settings = get_settings()
    backend = PostgresBackend(settings.database_url)
    await backend.initialize()
    set_backend(backend)
    yield backend
    await backend.close()


@pytest.mark.integration
async def test_tables_exist(pg_backend: PostgresBackend) -> None:
    pool = pg_backend._pool_or_raise()
    async with pool.acquire() as conn:
        tables = await conn.fetch(
            """
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
            """
        )
        names = {r["tablename"] for r in tables}
    assert {"entities", "edges", "observations"} <= names
    assert "persons" not in names
    assert "platform_identities" not in names


@pytest.mark.integration
async def test_vector_extension(pg_backend: PostgresBackend) -> None:
    pool = pg_backend._pool_or_raise()
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT extname FROM pg_extension WHERE extname = 'vector'"
        )
    assert result == "vector"


@pytest.mark.integration
async def test_insert_person_and_entity_and_edge(pg_backend: PostgresBackend) -> None:
    pool = pg_backend._pool_or_raise()
    async with pool.acquire() as conn:
        person_id = await conn.fetchval(
            """
            INSERT INTO entities (entity_type, platform, platform_entity_id, title, content)
            VALUES ('Person', 'canonical', 'test@example.com', 'Test User', 'test@example.com')
            ON CONFLICT (platform, platform_entity_id) DO UPDATE SET title = EXCLUDED.title
            RETURNING id
            """,
        )
        assert person_id is not None

        entity_id = await conn.fetchval(
            """
            INSERT INTO entities (entity_type, platform, platform_entity_id, title, content)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (platform, platform_entity_id) DO UPDATE SET title = EXCLUDED.title
            RETURNING id
            """,
            "Document",
            "gdocs",
            "test-doc-001",
            "Test Document",
            "Some content here",
        )
        assert entity_id is not None

        edge_id = await conn.fetchval(
            """
            INSERT INTO edges (edge_type, source_entity_id, target_entity_id)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            "authored",
            person_id,
            entity_id,
        )
        assert edge_id is not None

        await conn.execute("DELETE FROM entities WHERE id = $1", entity_id)
        count = await conn.fetchval("SELECT count(*) FROM edges WHERE id = $1", edge_id)
        assert count == 0

        await conn.execute("DELETE FROM entities WHERE id = $1", person_id)
