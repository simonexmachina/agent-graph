"""AgentGraph MCP server.

Exposes the knowledge graph as MCP tools so AI agents can search,
retrieve, and traverse entities directly.

Run via:
    agentgraph mcp
or via the `agentgraph/mcp` stdio transport understood by Claude Desktop
and other MCP clients.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from agentgraph.graph.query import (
    get_edges,
    get_entity,
    query_by_filter,
    search_entities,
    traverse_graph,
)

mcp = FastMCP("AgentGraph")


# ---------------------------------------------------------------------------
# search_entities — hybrid vector + full-text, RRF fused
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_entities_tool(
    query: str,
    entity_types: list[str] | None = None,
    limit: int = 10,
) -> str:
    """
    Search the knowledge graph using a natural-language query.

    Combines semantic vector similarity and full-text search via
    Reciprocal Rank Fusion for high-quality results.

    Args:
        query: Natural-language search query.
        entity_types: Optional list of entity types to restrict results
            (e.g. ["Message", "Document", "Channel"]).
        limit: Maximum number of results to return (default 10).

    Returns:
        JSON array of matching entities with id, title, content snippet,
        platform, and relevance score.
    """
    results = await search_entities(query, entity_types=entity_types, limit=limit)
    # Trim content to a readable snippet for the LLM
    for r in results:
        if r.get("content") and len(str(r["content"])) > 500:
            r["content"] = str(r["content"])[:500] + "…"
    return json.dumps(results, default=str)


# ---------------------------------------------------------------------------
# get_entity — full entity by UUID
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_entity_tool(entity_id: str) -> str:
    """
    Retrieve full details for a single entity by its UUID.

    Args:
        entity_id: The UUID of the entity (obtained from search results).

    Returns:
        JSON object with all entity fields, or an error message if not found.
    """
    entity = await get_entity(entity_id)
    if entity is None:
        return json.dumps({"error": f"Entity {entity_id!r} not found"})
    return json.dumps(entity, default=str)


# ---------------------------------------------------------------------------
# get_edges — edges connected to an entity
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_edges_tool(
    entity_id: str,
    edge_type: str | None = None,
    direction: str = "both",
) -> str:
    """
    List edges connected to an entity.

    Args:
        entity_id: UUID of the entity.
        edge_type: Optional edge type filter (e.g. "authored", "posted_in",
            "replied_to", "mentions", "collaborated").
        direction: "in" (incoming), "out" (outgoing), or "both" (default).

    Returns:
        JSON array of edge objects including source/target references.
    """
    edges = await get_edges(entity_id, edge_type=edge_type, direction=direction)
    return json.dumps(edges, default=str)


# ---------------------------------------------------------------------------
# traverse_graph — BFS neighbourhood
# ---------------------------------------------------------------------------

@mcp.tool()
async def traverse_graph_tool(
    entity_id: str,
    max_depth: int = 2,
) -> str:
    """
    Traverse the knowledge graph from a starting entity using BFS.

    Useful for discovering the context around a message or document:
    who authored it, which channel it appeared in, what it references, etc.

    Args:
        entity_id: UUID of the starting entity.
        max_depth: Maximum number of hops to traverse (default 2, max 4).

    Returns:
        JSON object with "nodes" (entities) and "edges" lists.
    """
    depth = min(max(max_depth, 1), 4)
    result = await traverse_graph(entity_id, max_depth=depth)
    # Trim content on nodes to keep response size manageable
    for node in result.get("nodes", []):
        if node.get("content") and len(str(node["content"])) > 300:
            node["content"] = str(node["content"])[:300] + "…"
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# query_by_filter — type + metadata filters
# ---------------------------------------------------------------------------

@mcp.tool()
async def query_by_filter_tool(
    entity_type: str,
    filters: dict[str, Any] | None = None,
    limit: int = 50,
) -> str:
    """
    Query entities by type with optional metadata key=value filters.

    Useful for listing all documents, all messages in a specific channel,
    or all tasks with a given status.

    Args:
        entity_type: Entity type to query ("Message", "Document",
            "Channel", "Task", "Project").
        filters: Optional dict of metadata key=value pairs to filter by.
        limit: Maximum number of results (default 50).

    Returns:
        JSON array of matching entities.
    """
    str_filters: dict[str, str] = {k: str(v) for k, v in (filters or {}).items()}
    results = await query_by_filter(entity_type, filters=str_filters, limit=limit)
    return json.dumps(results, default=str)
