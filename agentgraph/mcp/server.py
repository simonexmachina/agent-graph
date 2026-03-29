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
    min_score: float = 0.03,
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
        min_score: Minimum relevance score threshold (0–1, default 0.02).
            Results below this score are suppressed as noise.

    Returns:
        JSON array of matching entities with id, title, content snippet,
        platform, and relevance score.
    """
    results = await search_entities(query, entity_types=entity_types, limit=limit, min_score=min_score)
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
# fetch_entity — trigger connector re-ingestion
# ---------------------------------------------------------------------------

@mcp.tool()
async def fetch_entity_tool(platform: str, resource_id: str) -> str:
    """
    Trigger a connector fetch for a platform entity.

    Forces re-ingestion of a specific resource from its source platform,
    updating content and edges in the graph.

    Args:
        platform: Platform name (e.g. "gdocs", "slack", "discord", "gmail").
        resource_id: Platform-specific entity ID.

    Returns:
        JSON object with counts of ingested entities, persons, and edges.
    """
    from agentgraph.graph.fetch import fetch_entity

    try:
        result = await fetch_entity(platform, resource_id)
        return json.dumps(result)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# query_by_filter — type + metadata filters
# ---------------------------------------------------------------------------

@mcp.tool()
async def query_by_filter_tool(
    entity_type: str,
    filters: dict[str, Any] | None = None,
    since: str | None = None,
    authored_by_me: bool = False,
    limit: int = 50,
    order_by: str = "created_at",
) -> str:
    """
    Query entities by type with optional filters.

    Useful for listing all messages in a specific channel, all documents
    on a platform, activity within a time window, or content authored by
    the current user.

    Args:
        entity_type: Entity type to query ("Message", "Document",
            "Channel", "Task", "Project").
        filters: Optional dict of key=value filters. Known columns
            (platform, platform_entity_id) are applied as column filters;
            all other keys are matched against the metadata JSONB field.
        since: Optional time cutoff — ISO timestamp or relative duration
            like "12h", "30m", "2d". Only returns entities created after
            this time.
        authored_by_me: If true, only return entities with an authored
            edge from the current user (resolved from stored credentials).
        limit: Maximum number of results (default 50).
        order_by: Column to sort by descending (default "created_at").

    Returns:
        JSON array of matching entities.
    """
    str_filters: dict[str, str] = {k: str(v) for k, v in (filters or {}).items()}
    results = await query_by_filter(
        entity_type, filters=str_filters, limit=limit, order_by=order_by,
        since=since, authored_by_me=authored_by_me,
    )
    return json.dumps(results, default=str)
