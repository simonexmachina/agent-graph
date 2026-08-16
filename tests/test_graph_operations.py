"""Tests for transport-independent graph command orchestration."""

from __future__ import annotations

# pyright: reportPrivateUsage=false
import asyncio
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agentgraph.graph.operations import (
    get_entity_details,
    get_entity_edges,
    resolve_entity,
    summarize_entity,
    traverse_entity,
)


def _entity(
    entity_id: str,
    *,
    title: str = "Title",
    content: str = "Content",
) -> dict[str, Any]:
    return {
        "id": entity_id,
        "entity_type": "Document",
        "platform": "web",
        "platform_entity_id": entity_id,
        "title": title,
        "content": content,
        "metadata": {},
    }


@pytest.mark.asyncio
async def test_resolve_entity_uses_url_lookup_for_http_targets() -> None:
    entity = _entity("entity-id")
    with (
        patch(
            "agentgraph.graph.operations.get_entity_by_url",
            new=AsyncMock(return_value=entity),
        ) as get_by_url,
        patch("agentgraph.graph.operations.get_entity", new=AsyncMock()) as get_by_id,
    ):
        result = await resolve_entity("https://example.com/page")

    assert result == entity
    get_by_url.assert_awaited_once_with("https://example.com/page")
    get_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_entity_details_refreshes_requested_stub() -> None:
    stub = _entity("stub-id", title="", content="")
    refreshed = _entity("stub-id", title="Fetched", content="Source")
    with (
        patch("agentgraph.graph.operations.resolve_entity", new=AsyncMock(return_value=stub)),
        patch(
            "agentgraph.graph.operations.refresh_stub",
            new=AsyncMock(return_value=refreshed),
        ) as refresh_stub,
    ):
        result = await get_entity_details("stub-id", resolve=True)

    assert result == refreshed
    refresh_stub.assert_awaited_once_with(stub)


@pytest.mark.asyncio
async def test_get_entity_edges_uses_canonical_id() -> None:
    entity = _entity("canonical-id")
    edges = [{"edge_type": "references", "source_entity_id": "canonical-id"}]
    with (
        patch("agentgraph.graph.operations.resolve_entity", new=AsyncMock(return_value=entity)),
        patch(
            "agentgraph.graph.operations.get_edges",
            new=AsyncMock(return_value=edges),
        ) as get_edges,
    ):
        result_entity, result_edges = await get_entity_edges("can", direction="out")

    assert result_entity == entity
    assert result_edges == edges
    get_edges.assert_awaited_once_with("canonical-id", edge_type=None, direction="out")


@pytest.mark.asyncio
async def test_traverse_entity_refreshes_stubs_and_repeats_traversal() -> None:
    start = _entity("start")
    stub = _entity("stub", title="", content="")
    refreshed = _entity("stub", title="Fetched", content="Source")
    traversals = [
        {"nodes": [start, stub], "edges": []},
        {"nodes": [start, refreshed], "edges": []},
    ]
    with (
        patch("agentgraph.graph.operations.resolve_entity", new=AsyncMock(return_value=start)),
        patch(
            "agentgraph.graph.operations.traverse_graph",
            new=AsyncMock(side_effect=traversals),
        ) as traverse_graph,
        patch(
            "agentgraph.graph.operations.refresh_stub",
            new=AsyncMock(return_value=refreshed),
        ) as refresh_stub,
    ):
        entity, result = await traverse_entity("start", max_depth=2, resolve=True)

    assert entity == start
    assert result["nodes"][1]["title"] == "Fetched"
    refresh_stub.assert_awaited_once_with(stub)
    assert traverse_graph.await_count == 2


def test_summarize_entity_bounds_content_without_mutating_source() -> None:
    entity = _entity("entity-id", content="x" * 20)

    result = summarize_entity(entity, content_limit=10)

    assert result["content"] == "xxxxxxxxx…"
    assert result["content_truncated"] is True
    assert entity["content"] == "x" * 20


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sqlite_backends_can_write_to_same_wal_database(tmp_path: Path) -> None:
    from agentgraph.backends.sqlite.backend import SQLiteBackend
    from agentgraph.connectors.base import EntityBatch, EntityRecord

    database_path = tmp_path / "shared.db"
    server_backend = SQLiteBackend(str(database_path), vector_mode="bm25-only")
    cli_backend = SQLiteBackend(str(database_path), vector_mode="bm25-only")
    await server_backend.initialize()
    await cli_backend.initialize()
    try:
        await asyncio.gather(
            server_backend.upsert_batch(
                EntityBatch(
                    entities=[
                        EntityRecord(
                            entity_type="Document",
                            platform="server",
                            platform_entity_id="server-doc",
                            title="Server document",
                        )
                    ]
                ),
                person_embeddings={},
                entity_embeddings={},
            ),
            cli_backend.upsert_batch(
                EntityBatch(
                    entities=[
                        EntityRecord(
                            entity_type="Document",
                            platform="cli",
                            platform_entity_id="cli-doc",
                            title="CLI document",
                        )
                    ]
                ),
                person_embeddings={},
                entity_embeddings={},
            ),
        )

        assert await server_backend.get_entity_by_platform("cli", "cli-doc") is not None
        assert await cli_backend.get_entity_by_platform("server", "server-doc") is not None
    finally:
        await cli_backend.close()
        await server_backend.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sqlite_backends_do_not_reapply_schema_after_initialization(tmp_path: Path) -> None:
    from agentgraph.backends.sqlite.backend import SQLiteBackend

    database_path = tmp_path / "shared.db"
    first_backend = SQLiteBackend(str(database_path), vector_mode="bm25-only")
    await first_backend.initialize()
    await first_backend.close()

    backends = [SQLiteBackend(str(database_path), vector_mode="bm25-only") for _ in range(3)]
    try:
        with patch.object(SQLiteBackend, "_initialize_schema", new=AsyncMock()) as initialize_schema:
            await asyncio.gather(*(backend.initialize() for backend in backends))
        initialize_schema.assert_not_awaited()
    finally:
        await asyncio.gather(*(backend.close() for backend in backends))

    with sqlite3.connect(database_path) as conn:
        schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert schema_version == 2


@pytest.mark.asyncio
async def test_sqlite_initialization_failure_closes_connection(tmp_path: Path) -> None:
    from agentgraph.backends.sqlite.backend import SQLiteBackend

    backend = SQLiteBackend(str(tmp_path / "graph.db"), vector_mode="bm25-only")
    with (
        patch.object(backend, "_ensure_wal_mode", new=AsyncMock(side_effect=RuntimeError("locked"))),
        pytest.raises(RuntimeError, match="locked"),
    ):
        await backend.initialize()

    assert backend._conn is None
    assert backend._read_conn is None
