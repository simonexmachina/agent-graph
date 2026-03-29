"""Integration tests for the database schema."""

from __future__ import annotations

import pytest

from agentgraph.db.connection import apply_schema, get_pool, close_pool


@pytest.fixture(autouse=True)
async def db_pool():
    """Set up and tear down the connection pool for each test."""
    await apply_schema()
    yield
    await close_pool()


@pytest.mark.integration
async def test_tables_exist() -> None:
    pool = await get_pool()
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
async def test_vector_extension() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT extname FROM pg_extension WHERE extname = 'vector'"
        )
    assert result == "vector"


@pytest.mark.integration
async def test_insert_person_and_entity_and_edge() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Person is now an entity
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

        # Verify cascade: deleting entity removes edge
        await conn.execute("DELETE FROM entities WHERE id = $1", entity_id)
        count = await conn.fetchval("SELECT count(*) FROM edges WHERE id = $1", edge_id)
        assert count == 0

        # Clean up person
        await conn.execute("DELETE FROM entities WHERE id = $1", person_id)
