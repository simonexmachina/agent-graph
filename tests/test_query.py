"""Unit tests for the graph query layer and MCP tools (mocked DB)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entity(
    *,
    entity_type: str = "Document",
    platform: str = "gdocs",
    title: str = "Test Doc",
    content: str = "some content",
    score: float | None = None,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": str(uuid4()),
        "entity_type": entity_type,
        "platform": platform,
        "platform_entity_id": "pe-" + str(uuid4())[:8],
        "title": title,
        "content": content,
        "metadata": {},
        "created_at": None,
        "updated_at": None,
    }
    if score is not None:
        base["score"] = score
    return base


def _edge(
    *,
    edge_type: str = "authored",
    source_entity_id: str | None = None,
    target_entity_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "edge_type": edge_type,
        "platform": "gdocs",
        "properties": {},
        "source_entity_id": source_entity_id,
        "source_person_id": None,
        "target_entity_id": target_entity_id,
        "target_person_id": None,
        "source_ref": None,
        "target_ref": None,
    }


# ---------------------------------------------------------------------------
# search_entities
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_entities_returns_results() -> None:
    from agentgraph.graph.query import search_entities

    expected = [_entity(score=0.9), _entity(score=0.7)]

    with (
        patch("agentgraph.graph.query.encode", return_value=[0.1] * 384),
        patch("agentgraph.graph.query.get_pool") as mock_pool,
    ):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=_make_db_rows(expected))
        mock_pool.return_value = _pool_ctx(mock_conn)

        results = await search_entities("test query", limit=5)

    assert len(results) == 2
    assert results[0]["entity_type"] == "Document"


@pytest.mark.asyncio
async def test_search_entities_empty_results() -> None:
    from agentgraph.graph.query import search_entities

    with (
        patch("agentgraph.graph.query.encode", return_value=[0.0] * 384),
        patch("agentgraph.graph.query.get_pool") as mock_pool,
    ):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool.return_value = _pool_ctx(mock_conn)

        results = await search_entities("empty query")

    assert results == []


# ---------------------------------------------------------------------------
# get_entity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_entity_found() -> None:
    from agentgraph.graph.query import get_entity

    eid = str(uuid4())
    row = _make_db_row(_entity(title="Found Doc"))

    with patch("agentgraph.graph.query.get_pool") as mock_pool:
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=row)
        mock_pool.return_value = _pool_ctx(mock_conn)

        result = await get_entity(eid)

    assert result is not None
    assert result["title"] == "Found Doc"


@pytest.mark.asyncio
async def test_get_entity_not_found() -> None:
    from agentgraph.graph.query import get_entity

    with patch("agentgraph.graph.query.get_pool") as mock_pool:
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_pool.return_value = _pool_ctx(mock_conn)

        result = await get_entity(str(uuid4()))

    assert result is None


# ---------------------------------------------------------------------------
# get_edges
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_edges_returns_edges() -> None:
    from agentgraph.graph.query import get_edges

    eid = str(uuid4())
    edge = _edge(source_entity_id=eid)
    row = _make_db_row(edge, extra={"source_entity_ref": "pe-123", "target_entity_ref": None,
                                     "source_person_ref": None, "target_person_ref": None})

    with patch("agentgraph.graph.query.get_pool") as mock_pool:
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[row])
        mock_pool.return_value = _pool_ctx(mock_conn)

        edges = await get_edges(eid, direction="out")

    assert len(edges) == 1
    assert edges[0]["edge_type"] == "authored"


# ---------------------------------------------------------------------------
# MCP tool wrappers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mcp_search_entities_tool_returns_json() -> None:
    from agentgraph.mcp.server import search_entities_tool

    with patch("agentgraph.mcp.server.search_entities", new=AsyncMock(return_value=[])):
        result = await search_entities_tool("test")

    parsed = json.loads(result)
    assert isinstance(parsed, list)


@pytest.mark.asyncio
async def test_mcp_get_entity_tool_not_found() -> None:
    from agentgraph.mcp.server import get_entity_tool

    eid = str(uuid4())
    with patch("agentgraph.mcp.server.get_entity", new=AsyncMock(return_value=None)):
        result = await get_entity_tool(eid)

    parsed = json.loads(result)
    assert "error" in parsed


@pytest.mark.asyncio
async def test_mcp_get_entity_tool_found() -> None:
    from agentgraph.mcp.server import get_entity_tool

    eid = str(uuid4())
    fake_entity = _entity(title="My Doc")
    fake_entity["id"] = eid
    with patch("agentgraph.mcp.server.get_entity", new=AsyncMock(return_value=fake_entity)):
        result = await get_entity_tool(eid)

    parsed = json.loads(result)
    assert parsed["title"] == "My Doc"


@pytest.mark.asyncio
async def test_mcp_traverse_caps_depth() -> None:
    from agentgraph.mcp.server import traverse_graph_tool

    captured: dict[str, Any] = {}

    async def fake_traverse(entity_id: str, max_depth: int) -> dict[str, Any]:
        captured["depth"] = max_depth
        return {"nodes": [], "edges": []}

    with patch("agentgraph.mcp.server.traverse_graph", new=fake_traverse):
        await traverse_graph_tool(str(uuid4()), max_depth=99)

    assert captured["depth"] == 4  # capped at 4


@pytest.mark.asyncio
async def test_mcp_query_by_filter_tool() -> None:
    from agentgraph.mcp.server import query_by_filter_tool

    with patch("agentgraph.mcp.server.query_by_filter", new=AsyncMock(return_value=[])):
        result = await query_by_filter_tool("Message", filters={"channel_id": "C123"})

    parsed = json.loads(result)
    assert isinstance(parsed, list)


# ---------------------------------------------------------------------------
# DB mock helpers
# ---------------------------------------------------------------------------

def _make_db_rows(entities: list[dict[str, Any]]) -> list[Any]:
    return [_make_db_row(e) for e in entities]


def _make_db_row(d: dict[str, Any], extra: dict[str, Any] | None = None) -> Any:
    """Build a MagicMock that behaves like an asyncpg Record."""
    merged = {**d, **(extra or {})}
    row = MagicMock()
    row.__getitem__ = lambda self, key: merged[key]

    def keys_fn() -> list[str]:
        return list(merged.keys())

    row.keys = keys_fn
    row.get = lambda key, default=None: merged.get(key, default)
    # Support "key in row.keys()" checks
    return row


def _pool_ctx(mock_conn: Any) -> Any:
    """Return a mock pool whose acquire() is an async context manager."""
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)
    return pool
