"""Tests for connector-neutral command effects."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from agentgraph.backends.sqlite.backend import SQLiteBackend
from agentgraph.connectors.base import ConnectorCommandEffects, EntityReference
from agentgraph.connectors.command_effects import execute_deletions
from agentgraph.core.context import set_backend


@pytest.fixture()
async def sqlite_backend() -> AsyncGenerator[SQLiteBackend, None]:
    backend = SQLiteBackend(":memory:")
    await backend.initialize()
    set_backend(backend)
    yield backend
    await backend.close()


async def test_execute_deletions_removes_present_entities_and_edges(
    sqlite_backend: SQLiteBackend,
) -> None:
    conn = sqlite_backend._conn_or_raise()
    await conn.execute(
        """
        INSERT INTO entities (id, entity_type, platform, platform_entity_id)
        VALUES ('feed', 'Folder', 'rss', 'feed/example')
        """
    )
    await conn.execute(
        """
        INSERT INTO entities (id, entity_type, platform, platform_entity_id)
        VALUES ('article', 'Document', 'rss', 'entry/example')
        """
    )
    await conn.execute(
        """
        INSERT INTO edges (id, edge_type, source_entity_id, target_entity_id, platform)
        VALUES ('posted-in', 'posted_in', 'article', 'feed', 'rss')
        """
    )
    set_backend(sqlite_backend)

    deleted = await execute_deletions(
        ConnectorCommandEffects(
            delete_entities=(EntityReference("rss", "feed/example"),),
        )
    )

    assert [entity["id"] for entity in deleted] == ["feed"]
    assert await sqlite_backend.get_entity_by_id("feed") is None
    assert await sqlite_backend.get_entity_by_id("article") is not None
    assert await sqlite_backend._fetchval("SELECT count(*) FROM edges") == 0
