"""Tests for the /api/cli/browse endpoint."""

from __future__ import annotations

from pathlib import Path
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


def test_viewer_uses_bookmark_symbol_with_status() -> None:
    """The web viewer presents bookmark state with a compact symbol control."""
    viewer_html = Path("agentgraph/server/static/viewer.html").read_text()

    assert 'id="detail-bookmark"' in viewer_html
    assert 'id="detail-delete"' in viewer_html
    assert 'class="bookmark-glyph"' in viewer_html
    assert 'class="delete-glyph"' in viewer_html
    assert "Bookmark status" in viewer_html
    assert "aria-pressed" in viewer_html
    assert "applyZoomStyles();" in viewer_html
    assert "cy.style().update();" in viewer_html
    assert "/api/cli/delete" in viewer_html


def test_viewer_heading_links_to_empty_viewer_state() -> None:
    """The top-level product link clears all URL-backed viewer state."""
    viewer_html = Path("agentgraph/server/static/viewer.html").read_text()

    assert '<h1><a href="/viewer">AgentGraph</a></h1>' in viewer_html


def test_viewer_renders_standard_web_url_links() -> None:
    """Graph entities expose source links through the standard web_url metadata field."""
    viewer_html = Path("agentgraph/server/static/viewer.html").read_text()

    assert "function getPlatformUrl(entity)" in viewer_html
    assert "metadata.web_url" in viewer_html
    assert "isHttpUrl(metadata.web_url) ? metadata.web_url : null" in viewer_html
    assert "metadata.link" not in viewer_html
    assert "metadata.feed_url" not in viewer_html
    assert "detailBody.appendChild(row('Link', linkHtml))" in viewer_html


def test_viewer_defaults_prioritize_readable_node_labels() -> None:
    """The graph's initial layout leaves room for node labels."""
    viewer_html = Path("agentgraph/server/static/viewer.html").read_text()

    assert "const DEFAULT_MIN_READABLE_ZOOM = 1;" in viewer_html
    assert "const DEFAULT_LAYOUT_PADDING = 60;" in viewer_html
    assert "const READABLE_GRID_CELL_WIDTH = 165;" in viewer_html
    assert "const READABLE_GRID_CELL_HEIGHT = 90;" in viewer_html
    assert "function ensureReadableDefaultZoom()" in viewer_html
    assert "function readableGridPositionFor(index, count)" in viewer_html
    assert "function readableGridPositions()" in viewer_html
    assert "window.__agentGraphViewer = { cy };" in viewer_html
    assert "name: 'preset'" in viewer_html
    assert "positions: readableGridPositions()" in viewer_html
    assert "nodeDimensionsIncludeLabels: true" in viewer_html
    assert "nodeRepulsion: () => 800000" in viewer_html
    assert "idealEdgeLength: () => 180" in viewer_html
    assert "nodeOverlap: 30" in viewer_html
    assert "ensureReadableDefaultZoom();" in viewer_html
    assert "cy.zoom(DEFAULT_MIN_READABLE_ZOOM);" in viewer_html


def test_viewer_has_remote_list_mode() -> None:
    """The viewer uses the node and edge endpoints independently in list/graph modes."""
    viewer_html = Path("agentgraph/server/static/viewer.html").read_text()

    assert 'id="graph-tab"' in viewer_html
    assert 'id="list-tab"' in viewer_html
    assert "tabulator-tables@6.3.1" in viewer_html
    assert "/api/cli/browse/nodes" in viewer_html
    assert "/api/cli/browse/edges" in viewer_html
    assert "paginationMode: 'remote'" in viewer_html
    assert "sortMode: 'remote'" in viewer_html
    assert "paginationSize: Number(limitSlider.value)" in viewer_html
    assert "listTable.setPageSize(params.limit)" in viewer_html
    assert "paginationSizeSelector" not in viewer_html
    assert "function renderCachedGraph(params)" in viewer_html
    assert "function renderCachedList(params)" in viewer_html
    assert "renderCachedList(params)" in viewer_html
    assert "cy.resize();" in viewer_html
    assert ".tabulator:has(.tabulator-alert) .tabulator-placeholder" in viewer_html
    assert "return currentView() === 'list';" in viewer_html
    assert "if (listTable.getPageSize() !== params.limit) return false;" in viewer_html


def test_viewer_list_rows_match_graph_click_behaviour() -> None:
    """List row clicks open details and double clicks focus the selected node."""
    viewer_html = Path("agentgraph/server/static/viewer.html").read_text()

    assert "rowClick(_event, row) { showEntityDetail(row.getData().id); }" in viewer_html
    assert "rowDblClick(_event, row) { focusNode(row.getData().id); }" in viewer_html
    assert "function focusNode(entityId)" in viewer_html
    assert "focusNode(node.data('id'));" in viewer_html


def test_viewer_omits_redundant_all_type_filter() -> None:
    """The default all-types view should use the database's global sort index."""
    viewer_html = Path("agentgraph/server/static/viewer.html").read_text()
    assert "function activeEntityTypes()" in viewer_html
    assert "return allTypesSelected ? undefined : selected;" in viewer_html
    assert "entity_type: activeEntityTypes()," in viewer_html


def test_viewer_has_focus_node_reset_control() -> None:
    """The Focus Node section can be cleared without resetting other filters."""
    viewer_html = Path("agentgraph/server/static/viewer.html").read_text()
    assert 'id="focus-reset-btn"' in viewer_html
    assert "refreshGraph({ node_id: null, depth: 1 });" in viewer_html
    assert "lookupError.style.display = 'none';" in viewer_html


def test_viewer_focus_node_placeholder_describes_supported_identifiers() -> None:
    """The Focus Node hint describes each connector-neutral lookup format."""
    viewer_html = Path("agentgraph/server/static/viewer.html").read_text()

    assert 'placeholder="Entity UUID, prefix, or platform reference"' in viewer_html


def test_viewer_text_inputs_submit_on_enter_or_blur() -> None:
    """Text queries wait for an explicit Enter or focus-loss submission."""
    viewer_html = Path("agentgraph/server/static/viewer.html").read_text()

    assert "function wireTextInputSubmission(input, submit)" in viewer_html
    assert "input.addEventListener('keydown'" in viewer_html
    assert "input.addEventListener('blur', submitIfChanged)" in viewer_html
    assert "wireTextInputSubmission(\n    searchInput" in viewer_html
    assert "wireTextInputSubmission(lookupInput" in viewer_html
    assert "searchInput.addEventListener('input'" not in viewer_html
    assert "lookupInput.addEventListener('keydown'" not in viewer_html


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


@pytest.mark.asyncio
async def test_browse_nodes_include_display_name_from_title() -> None:
    """Viewer nodes include a human label derived from title."""
    from agentgraph.server.cli_api import cli_browse

    thread = _entity(
        entity_type="Thread",
        platform="gmail",
        title="Quarterly planning sync with vendor and finance",
    )

    with patch("agentgraph.server.cli_api.get_entity", AsyncMock(return_value=None)), \
         patch("agentgraph.server.cli_api.traverse_graph", AsyncMock(return_value={"nodes": [], "edges": []})), \
         patch("agentgraph.server.cli_api.search_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.list_entities", AsyncMock(return_value=[thread])), \
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

    assert result["nodes"][0]["display_name"] == thread["title"]


@pytest.mark.asyncio
async def test_browse_nodes_fall_back_to_content_for_display_name() -> None:
    """Viewer nodes fall back to normalised content when title is missing."""
    from agentgraph.server.cli_api import cli_browse

    message = _entity(entity_type="Message", title="")
    message["content"] = "  First line\nwith extra   spacing  "

    with patch("agentgraph.server.cli_api.get_entity", AsyncMock(return_value=None)), \
         patch("agentgraph.server.cli_api.traverse_graph", AsyncMock(return_value={"nodes": [], "edges": []})), \
         patch("agentgraph.server.cli_api.search_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.list_entities", AsyncMock(return_value=[message])), \
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

    assert result["nodes"][0]["display_name"] == "First line with extra spacing"
    assert result["nodes"][0]["viewer_label"] == "First line with extra spacing"


@pytest.mark.asyncio
async def test_browse_message_nodes_include_truncated_viewer_label() -> None:
    """Message nodes expose a shortened label for graph rendering."""
    from agentgraph.server.cli_api import cli_browse

    message = _entity(entity_type="Message", title="")
    message["content"] = (
        "This is a long message body that should be truncated in the viewer label "
        "while keeping the full display name available in the detail view."
    )

    with patch("agentgraph.server.cli_api.get_entity", AsyncMock(return_value=None)), \
         patch("agentgraph.server.cli_api.traverse_graph", AsyncMock(return_value={"nodes": [], "edges": []})), \
         patch("agentgraph.server.cli_api.search_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.list_entities", AsyncMock(return_value=[message])), \
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

    node = result["nodes"][0]
    assert node["display_name"].endswith("detail view.")
    assert node["viewer_label"].endswith("…")
    assert len(node["viewer_label"]) <= 80


@pytest.mark.asyncio
async def test_browse_nodes_preserve_bookmarked_flag() -> None:
    """Viewer nodes expose bookmark state for graph styling and detail actions."""
    from agentgraph.server.cli_api import cli_browse

    document = _entity(entity_type="Document", title="Pinned Doc")
    document["bookmarked"] = True

    with patch("agentgraph.server.cli_api.get_entity", AsyncMock(return_value=None)), \
         patch("agentgraph.server.cli_api.traverse_graph", AsyncMock(return_value={"nodes": [], "edges": []})), \
         patch("agentgraph.server.cli_api.search_entities", AsyncMock(return_value=[])), \
         patch("agentgraph.server.cli_api.list_entities", AsyncMock(return_value=[document])), \
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

    assert result["nodes"][0]["bookmarked"] is True


# ---------------------------------------------------------------------------
# 404 when node_id not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_browse_404_when_node_id_not_found() -> None:
    """Returns 404 when the specified node_id does not exist."""
    from fastapi import HTTPException

    from agentgraph.server.cli_api import cli_browse

    with patch("agentgraph.server.cli_api.get_entity", AsyncMock(return_value=None)), \
         pytest.raises(HTTPException) as exc_info:
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


@pytest.mark.asyncio
async def test_browse_nodes_returns_paginated_node_page() -> None:
    """The list endpoint exposes Tabulator-compatible pagination metadata."""
    from agentgraph.server.cli_api import cli_browse_nodes

    entities = [_entity(title="First"), _entity(title="Second")]
    mock_page = AsyncMock(return_value=(entities, 7))

    with patch("agentgraph.server.cli_api.list_entities_page", mock_page):
        result = await cli_browse_nodes(
            search=None,
            entity_type=[],
            platform=None,
            since=None,
            node_id=None,
            depth=2,
            limit=100,
            page=2,
            size=2,
            sort="updated_at",
            sort_dir="asc",
        )

    assert [node["display_name"] for node in result["data"]] == ["First", "Second"]
    assert result["total"] == 7
    assert result["last_page"] == 4
    mock_page.assert_awaited_once_with(
        entity_types=None,
        platform=None,
        since=None,
        limit=2,
        offset=2,
        order_by="updated_at",
        order_dir="asc",
    )


@pytest.mark.asyncio
async def test_browse_edges_accepts_comma_separated_node_ids() -> None:
    """Edge lookup deduplicates node IDs and omits edges outside the visible set."""
    from agentgraph.server.cli_api import cli_browse_edges

    first = _entity()
    second = _entity()
    outside = _entity()
    visible_edge = _edge(first["id"], second["id"])
    hidden_edge = _edge(first["id"], outside["id"])
    mock_edges = AsyncMock(return_value=[visible_edge, hidden_edge])

    with patch("agentgraph.server.cli_api.get_edges_for_entities", mock_edges):
        result = await cli_browse_edges(f" {first['id']}, {second['id']}, {first['id']} ")

    assert result == {"edges": [visible_edge]}
    mock_edges.assert_awaited_once_with([first["id"], second["id"]])
