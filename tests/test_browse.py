"""Tests for the /api/cli/browse endpoint."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agentgraph.core.context import set_backend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entity(
    *,
    entity_type: str = "Document",
    platform: str = "gdocs",
    title: str = "Test",
) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "entity_type": entity_type,
        "platform": platform,
        "platform_entity_id": "pe-" + str(uuid4())[:8],
        "title": title,
        "content": "",
        "metadata": {},
        "created_at": None,
        "updated_at": "2025-01-01T00:00:00",
    }


def _edge(src: str, tgt: str, edge_type: str = "authored") -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "edge_type": edge_type,
        "platform": "gdocs",
        "properties": {},
        "source_entity_id": src,
        "target_entity_id": tgt,
        "source_ref": None,
        "target_ref": None,
    }


def _mock_backend(**overrides: Any) -> Any:
    backend = MagicMock()
    defaults: dict[str, Any] = {
        "search_entities": AsyncMock(return_value=[]),
        "get_entity_by_id": AsyncMock(return_value=None),
        "get_entities_by_id_prefix": AsyncMock(return_value=[]),
        "get_entity_by_platform": AsyncMock(return_value=None),
        "get_entities_by_ids": AsyncMock(return_value=[]),
        "get_edges_for_entities": AsyncMock(return_value=[]),
        "traverse_graph": AsyncMock(return_value={"nodes": [], "edges": []}),
        "list_entities": AsyncMock(return_value=[]),
        "touch_last_accessed_by_ids": AsyncMock(return_value=None),
    }
    for name, value in {**defaults, **overrides}.items():
        setattr(backend, name, value)
    return backend


# ---------------------------------------------------------------------------
# Rule: focal node always shown regardless of filters
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_focal_node_shown_when_type_filter_excludes_it() -> None:
    """node_id entity is always in results even if entity_type filter would exclude it."""
    from agentgraph.server.cli_api import cli_browse

    focal = _entity(entity_type="Person", platform="slack")
    neighbour = _entity(entity_type="Document")
    edge = _edge(focal["id"], neighbour["id"])

    backend = _mock_backend(
        get_entity_by_id=AsyncMock(return_value=focal),
        traverse_graph=AsyncMock(return_value={"nodes": [focal, neighbour], "edges": [edge]}),
        list_entities=AsyncMock(return_value=[]),
    )
    set_backend(backend)

    with patch("agentgraph.server.cli_api.get_entity", AsyncMock(return_value=focal)), \
         patch("agentgraph.server.cli_api.traverse_graph", AsyncMock(return_value={"nodes": [focal, neighbour], "edges": [edge]})), \
         patch("agentgraph.server.cli_api.search_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.list_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.get_edges_for_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.get_entities_by_ids", AsyncMock(return_value=[])):
        result = await cli_browse(
            node_id=focal["id"],
            entity_type=["Document"],  # excludes Person
            search=None,
            platform=None,
            since=None,
            depth=2,
            limit=50,
        )

    node_ids = {n["id"] for n in result["nodes"]}
    assert focal["id"] in node_ids, "Focal node must always be present"


# ---------------------------------------------------------------------------
# Rule: only matching nodes shown (except focal)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_entity_type_filter_excludes_non_focal_nodes() -> None:
    """Non-focal nodes that don't match entity_type filter are excluded."""
    from agentgraph.server.cli_api import cli_browse

    focal = _entity(entity_type="Person", platform="slack")
    doc = _entity(entity_type="Document")
    msg = _entity(entity_type="Message")
    edge_doc = _edge(focal["id"], doc["id"])
    edge_msg = _edge(focal["id"], msg["id"])

    traverse_result = {"nodes": [focal, doc, msg], "edges": [edge_doc, edge_msg]}

    with patch("agentgraph.server.cli_api.get_entity", AsyncMock(return_value=focal)), \
         patch("agentgraph.server.cli_api.traverse_graph", AsyncMock(return_value=traverse_result)), \
         patch("agentgraph.server.cli_api.search_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.list_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.get_edges_for_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.get_entities_by_ids", AsyncMock(return_value=[])):
        result = await cli_browse(
            node_id=focal["id"],
            entity_type=["Person", "Document"],  # excludes Message
            search=None,
            platform=None,
            since=None,
            depth=2,
            limit=50,
        )

    node_ids = {n["id"] for n in result["nodes"]}
    assert msg["id"] not in node_ids, "Message node should be filtered out"
    assert doc["id"] in node_ids
    assert focal["id"] in node_ids


# ---------------------------------------------------------------------------
# Rule: depth only applies when node_id provided
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_depth_ignored_without_node_id() -> None:
    """When no node_id is given, traverse_graph is never called."""
    from agentgraph.server.cli_api import cli_browse

    mock_traverse = AsyncMock(return_value={"nodes": [], "edges": []})

    with patch("agentgraph.server.cli_api.get_entity", AsyncMock(return_value=None)), \
         patch("agentgraph.server.cli_api.traverse_graph", mock_traverse), \
         patch("agentgraph.server.cli_api.search_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.list_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.get_edges_for_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.get_entities_by_ids", AsyncMock(return_value=[])):
        await cli_browse(
            node_id=None,
            entity_type=[],
            search=None,
            platform=None,
            since=None,
            depth=4,
            limit=50,
        )

    mock_traverse.assert_not_called()


@pytest.mark.asyncio
async def test_traverse_called_with_depth_when_node_id_given() -> None:
    """When node_id is given, traverse_graph is called with the specified depth."""
    from agentgraph.server.cli_api import cli_browse

    focal = _entity(entity_type="Person")
    mock_traverse = AsyncMock(return_value={"nodes": [focal], "edges": []})

    with patch("agentgraph.server.cli_api.get_entity", AsyncMock(return_value=focal)), \
         patch("agentgraph.server.cli_api.traverse_graph", mock_traverse), \
         patch("agentgraph.server.cli_api.search_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.list_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.get_edges_for_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.get_entities_by_ids", AsyncMock(return_value=[])):
        await cli_browse(
            node_id=focal["id"],
            entity_type=[],
            search=None,
            platform=None,
            since=None,
            depth=3,
            limit=50,
        )

    mock_traverse.assert_called_once_with(focal["id"], max_depth=3)


# ---------------------------------------------------------------------------
# Reachability prune
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reachability_prune_removes_disconnected_nodes() -> None:
    """Nodes not reachable from focal through the filtered edge set are pruned."""
    from agentgraph.server.cli_api import cli_browse

    focal = _entity(entity_type="Person")
    connected = _entity(entity_type="Message")
    orphan = _entity(entity_type="Message")
    edge = _edge(focal["id"], connected["id"])
    # orphan has no edge connecting it to focal in this filtered view

    traverse_result = {"nodes": [focal, connected, orphan], "edges": [edge]}

    with patch("agentgraph.server.cli_api.get_entity", AsyncMock(return_value=focal)), \
         patch("agentgraph.server.cli_api.traverse_graph", AsyncMock(return_value=traverse_result)), \
         patch("agentgraph.server.cli_api.search_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.list_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.get_edges_for_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.get_entities_by_ids", AsyncMock(return_value=[])):
        result = await cli_browse(
            node_id=focal["id"],
            entity_type=[],
            search=None,
            platform=None,
            since=None,
            depth=2,
            limit=50,
        )

    node_ids = {n["id"] for n in result["nodes"]}
    assert orphan["id"] not in node_ids, "Disconnected node should be pruned"
    assert connected["id"] in node_ids
    assert focal["id"] in node_ids


# ---------------------------------------------------------------------------
# No node_id — list_entities path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_node_id_returns_list_entities() -> None:
    """Without node_id or search, list_entities is used."""
    from agentgraph.server.cli_api import cli_browse

    entities = [_entity(), _entity()]
    mock_list = AsyncMock(return_value=entities)

    with patch("agentgraph.server.cli_api.get_entity", AsyncMock(return_value=None)), \
         patch("agentgraph.server.cli_api.traverse_graph", AsyncMock(return_value={"nodes": [], "edges": []})), \
         patch("agentgraph.server.cli_api.search_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.list_entities", mock_list), \
         patch("agentgraph.server.cli_api.get_edges_for_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.get_entities_by_ids", AsyncMock(return_value=[])):
        result = await cli_browse(
            node_id=None,
            entity_type=[],
            search=None,
            platform=None,
            since=None,
            depth=2,
            limit=50,
        )

    assert len(result["nodes"]) == 2
    mock_list.assert_called_once()


# ---------------------------------------------------------------------------
# Search + node_id intersection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_with_node_id_intersects_neighbourhood() -> None:
    """Search results are intersected with the neighbourhood when node_id is given."""
    from agentgraph.server.cli_api import cli_browse

    focal = _entity(entity_type="Person")
    in_neighbourhood = _entity(entity_type="Document", title="Match")
    outside_neighbourhood = _entity(entity_type="Document", title="Match too")
    edge = _edge(focal["id"], in_neighbourhood["id"])

    traverse_result = {
        "nodes": [focal, in_neighbourhood],
        "edges": [edge],
    }
    search_results = [in_neighbourhood, outside_neighbourhood]

    with patch("agentgraph.server.cli_api.get_entity", AsyncMock(return_value=focal)), \
         patch("agentgraph.server.cli_api.traverse_graph", AsyncMock(return_value=traverse_result)), \
         patch("agentgraph.server.cli_api.search_entities", AsyncMock(return_value=search_results)), \
         patch("agentgraph.server.cli_api.list_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.get_edges_for_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.get_entities_by_ids", AsyncMock(return_value=[])):
        result = await cli_browse(
            node_id=focal["id"],
            entity_type=[],
            search="Match",
            platform=None,
            since=None,
            depth=2,
            limit=50,
        )

    node_ids = {n["id"] for n in result["nodes"]}
    assert outside_neighbourhood["id"] not in node_ids
    assert in_neighbourhood["id"] in node_ids
    assert focal["id"] in node_ids  # focal always present


# ---------------------------------------------------------------------------
# 404 when node_id not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_browse_404_when_node_id_not_found() -> None:
    """Returns 404 when the specified node_id does not exist."""
    from fastapi import HTTPException
    from agentgraph.server.cli_api import cli_browse

    with patch("agentgraph.server.cli_api.get_entity", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc_info:
            await cli_browse(
                node_id="nonexistent-id",
                entity_type=[],
                search=None,
                platform=None,
                since=None,
                depth=2,
                limit=50,
            )

    assert exc_info.value.status_code == 404
