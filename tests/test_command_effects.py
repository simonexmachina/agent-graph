"""Tests for connector-neutral command effects."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest

from agentgraph.backends.sqlite.backend import SQLiteBackend
from agentgraph.connectors.base import (
    ConnectorCommandEffects,
    EntityBatch,
    EntityRecord,
    EntityReference,
    SourceReference,
)
from agentgraph.connectors.command_effects import execute_deletions, execute_fetches
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


async def test_execute_fetches_passes_metadata_and_upserts_batch() -> None:
    batch = EntityBatch(
        entities=[
            EntityRecord(
                entity_type="Document",
                platform="web",
                platform_entity_id="https://example.com/page",
            )
        ]
    )

    class Connector:
        fetch = AsyncMock(return_value=batch)

    upsert = AsyncMock()
    effects = ConnectorCommandEffects(
        fetch_references=(
            SourceReference(
                source="web",
                resource_type="document",
                resource_id="https://example.com/page",
                fetch_meta={"compact_html": "true"},
            ),
        )
    )
    with (
        patch("agentgraph.connectors.registry.get_connector", return_value=Connector()),
        patch("agentgraph.graph.upsert.upsert_batch", new=upsert),
    ):
        result = await execute_fetches(effects)

    Connector.fetch.assert_awaited_once_with(
        resource_type="document",
        resource_id="https://example.com/page",
        meta={"compact_html": "true"},
    )
    upsert.assert_awaited_once_with(batch)
    assert result == [
        {
            "source": "web",
            "resource_type": "document",
            "resource_id": "https://example.com/page",
            "entities": 1,
            "persons": 0,
            "edges": 0,
        }
    ]
