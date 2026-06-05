"""AgentGraph MCP server.

Exposes the knowledge graph as MCP tools so AI agents can search,
retrieve, and traverse entities directly.

Run via:
    agentgraph mcp
or via the `agentgraph/mcp` stdio transport understood by Claude Desktop
and other MCP clients.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from agentgraph.core.context import get_backend
from agentgraph.graph.query import (
    get_edges,
    get_entity,
    query_by_filter,
    search_entities,
    traverse_graph,
)

logger = logging.getLogger(__name__)
mcp = FastMCP("AgentGraph")

# ---------------------------------------------------------------------------
# list_connectors — connector discovery for agents
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_connectors_tool() -> str:
    """
    List all installed connectors and their capabilities.

    Call this first to understand which data sources are available and
    which platform values are valid for the platform= parameter in other
    tools (search_entities_tool, query_by_filter_tool, fetch_entity_tool).

    Returns:
        JSON array of connector objects, each with:
          - source: platform name to pass as the platform= argument
          - description: what this connector ingests
          - auth_provider: shared auth provider key (e.g. "google")
          - auth_status: "ok" | "missing" | "invalid"
          - auth_detail: aggregate auth summary or error message; null if missing
          - shared_auth: true when multiple connectors share the same auth provider
          - account_count: number of authenticated accounts for that provider
          - url_patterns: URL patterns this connector recognises
          - polls: true if this connector has its own background poll
          - poll_interval_seconds: direct poll interval, or null
          - poll_delegates: connector sources refreshed by this connector's poll
          - polled_by: connector sources whose poll refreshes this connector
          - sync: human-readable sync summary
          - last_synced_at: latest entity sync timestamp for this connector source, or null
          - last_sync: human-readable last-sync label
    """
    from agentgraph.connectors.registry import bootstrap, get_all_connectors
    from agentgraph.connectors.status import connector_status_items

    bootstrap()
    all_connectors = get_all_connectors()
    result = await connector_status_items(all_connectors, get_backend())
    return json.dumps(result)


@mcp.tool()
async def list_auth_providers_tool() -> str:
    """
    List authentication providers and their current account/auth state.

    Returns:
        JSON array of auth provider objects, each with:
          - provider: auth provider key such as "google" or "slack"
          - description: provider summary
          - connectors: connector sources that use this provider
          - shared: true when multiple connectors use the same provider
          - auth_status: "ok" | "missing" | "invalid"
          - auth_detail: aggregate auth summary or error message; null if missing
          - accounts: authenticated account rows with account_id, label, workspace_id,
            email, auth_status, and auth_detail
    """
    from agentgraph.connectors.registry import bootstrap, get_all_connectors
    from agentgraph.connectors.status import auth_provider_status_items

    bootstrap()
    result = await auth_provider_status_items(get_all_connectors())
    return json.dumps(result)


@mcp.tool()
async def run_connector_command_tool(source: str, args: list[str]) -> str:
    """
    Run a connector-owned command.

    This is the MCP equivalent of:
        agentgraph connector <source> <args...>

    Core dispatches to the connector generically; the connector owns command
    names, argument parsing, and behaviour.

    Args:
        source: Connector source, e.g. "rss".
        args: Connector command and arguments, e.g.
            ["add", "https://simonwillison.net/atom/everything/"].
            RSS OPML import is also available as:
            ["import-opml", "/path/to/feeds.opml", "--all"] or
            ["import-opml", "/path/to/feeds.opml", "--select", "1,3-5"].

    Returns:
        JSON object returned by the connector, or an error.
    """
    from agentgraph.connectors.registry import bootstrap, get_connector

    bootstrap()
    connector = get_connector(source)
    if connector is None:
        return json.dumps({"error": f"Unknown connector {source!r}"})
    try:
        result = type(connector).run_cli_command(args)
        return json.dumps(result, default=str)
    except (NotImplementedError, ValueError) as exc:
        return json.dumps({"error": str(exc)})


async def _refresh_discord_attachments(results: list[dict[str, Any]]) -> None:
    """Refresh Discord CDN attachment URLs in-place for all results that need it.

    Discord signed CDN URLs expire shortly after ingestion. For any Discord
    Message entity whose metadata contains attachments, fetch fresh URLs from
    the Discord API concurrently and update the metadata in-place.
    Silently skips on missing credentials or any API error.
    """
    try:
        from agentgraph_connector_discord import refresh_attachment_urls
    except ImportError:
        return

    async def _refresh_one(entity: dict[str, Any]) -> None:
        meta = entity.get("metadata")
        if not isinstance(meta, dict):
            return
        stored_json: str | None = meta.get("attachments")
        if not stored_json:
            return
        channel_id: str = meta.get("channel_id", "")
        message_id: str = meta.get("message_id", "")
        if not channel_id or not message_id:
            return
        fresh_json = await refresh_attachment_urls(channel_id, message_id, stored_json)
        meta["attachments"] = fresh_json

    discord_messages = [
        e for e in results
        if e.get("platform") == "discord" and e.get("entity_type") == "Message"
    ]
    if discord_messages:
        await asyncio.gather(*(_refresh_one(e) for e in discord_messages))


# ---------------------------------------------------------------------------
# search_entities — hybrid vector + full-text, RRF fused
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_entities_tool(
    query: str,
    entity_types: list[str] | None = None,
    platform: str | None = None,
    limit: int = 10,
    min_score: float = 0.03,
) -> str:
    """
    Search the knowledge graph using a natural-language query.

    Combines semantic vector similarity and full-text search via
    Reciprocal Rank Fusion for high-quality results.

    IMPORTANT — images and file attachments: photos, images, and uploaded
    files are stored as attachments on Message entities (in
    metadata.attachments), NOT as Document entities. If the user asks
    about images, photos, pictures, or uploaded files, search Message
    entities or use query_by_filter_tool with has_attachments=True.
    Do NOT query Document for images — Documents are text documents only.

    Args:
        query: Natural-language search query.
        entity_types: Optional list of entity types to restrict results
            (e.g. ["Message", "Document", "Channel"]). To find images or
            attachments, pass ["Message"].
        platform: Optional platform name to scope the search to a single
            source (e.g. "slack", "discord", "gdocs", "gmail", "rss"). When
            omitted, all platforms are searched. Use this to avoid
            cross-platform noise when the user specifies a source.
        limit: Maximum number of results to return (default 10).
        min_score: Minimum relevance score threshold (0–1, default 0.02).
            Results below this score are suppressed as noise.

    Returns:
        JSON array of matching entities with id, title, content snippet,
        platform, and relevance score. Discord attachment URLs are
        automatically refreshed before returning so they are valid at
        the time of the call.
    """
    results = await search_entities(
        query, entity_types=entity_types, limit=limit, min_score=min_score, platform=platform
    )
    for r in results:
        if r.get("content") and len(str(r["content"])) > 500:
            r["content"] = str(r["content"])[:500] + "…"
    await _refresh_discord_attachments(results)
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
        platform: Platform name (e.g. "gdocs", "slack", "discord", "gmail", "rss").
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
# fetch_entity_by_id — re-ingest by internal UUID
# ---------------------------------------------------------------------------

@mcp.tool()
async def fetch_entity_by_id_tool(entity_id: str) -> str:
    """
    Trigger a connector fetch for an entity by its internal UUID.

    Looks up the entity's platform and platform-specific ID, then forces
    re-ingestion from the source platform.

    Args:
        entity_id: Internal entity UUID (the id field from graph nodes).

    Returns:
        JSON object with counts of ingested entities, persons, and edges,
        or an error message if the entity is not found.
    """
    from agentgraph.graph.fetch import fetch_entity_by_id

    try:
        result = await fetch_entity_by_id(entity_id)
        return json.dumps(result)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# download_entity — authenticated source-file download
# ---------------------------------------------------------------------------

@mcp.tool()
async def download_entity_tool(entity_id: str, output_path: str | None = None) -> str:
    """
    Download an entity's source file using the connector's stored auth.

    Supports entity UUIDs, UUID prefixes, and platform refs such as
    "gdrive/file-id" when those resolve to a graph entity. The file is written
    to output_path when supplied, or to the MCP server's current directory using
    the source filename.

    Args:
        entity_id: Entity UUID, UUID prefix, or platform/entity_id reference.
        output_path: Optional output file path or directory.

    Returns:
        JSON object with path, byte count, filename, platform, and MIME type, or
        an error message if the entity or connector cannot be downloaded.
    """
    from agentgraph.graph.download import download_entity

    try:
        result = await download_entity(entity_id, output_path)
        return json.dumps(result, default=str)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# unify_persons — manually merge duplicate Person entities
# ---------------------------------------------------------------------------

@mcp.tool()
async def unify_persons_tool(
    primary_entity_id: str,
    duplicate_entity_ids: list[str],
) -> str:
    """
    Merge duplicate Person entities that refer to the same human.

    Use this only when the user has confirmed that the Person entities are the
    same person. The primary Person keeps its ID; edges from duplicate Persons
    are rewired to the primary; duplicate metadata such as platform user IDs is
    folded into the primary; duplicate Person entities are removed.

    Args:
        primary_entity_id: Person entity ID, UUID prefix, or platform ref to keep.
        duplicate_entity_ids: Duplicate Person entity IDs, UUID prefixes, or
            platform refs to merge into the primary.

    Returns:
        JSON object with the updated primary Person and merged duplicate IDs,
        or an error message if any entity is missing or is not a Person.
    """
    from agentgraph.graph.person import unify_persons

    try:
        result = await unify_persons(primary_entity_id, duplicate_entity_ids)
        return json.dumps(result, default=str)
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
    has_attachments: bool = False,
    limit: int = 50,
    order_by: str = "created_at",
) -> str:
    """
    Query entities by type with optional filters.

    Useful for listing all messages in a specific channel, all documents
    on a platform, activity within a time window, or content authored by
    the current user.

    Entity types and what they contain:
      - Message: chat messages from Discord, Slack, Gmail, etc. This is
          also where image and file uploads live — attachments are stored
          in metadata.attachments as a JSON array with fields: url,
          filename, content_type, width, height. To find images or
          uploaded files, query Message (not Document) and set
          has_attachments=True.
      - Document: text documents such as Google Docs. Does NOT contain
          image or file attachments — those are on Message entities.
      - Spreadsheet: Google Sheets or Excel files.
      - Folder: a Google Drive folder containing other entities.
      - Channel: a chat channel or DM thread (Discord, Slack, etc.).
      - Thread: an email thread (Gmail).
      - Task: a task or to-do item (e.g. from a project tracker).
      - Project: a project or repository container.

    Example — find images uploaded in the last 7 days:
        entity_type="Message", has_attachments=True, since="7d"

    Args:
        entity_type: Entity type to query. See above for what each type
            contains. Use "Message" to find images/attachments.
        filters: Optional dict of key=value filters. Known columns
            (platform, platform_entity_id) are applied as column filters;
            all other keys are matched against the metadata JSONB field.
        since: Optional time cutoff — ISO timestamp or relative duration
            like "12h", "30m", "2d". Only returns entities updated after
            this time.
        authored_by_me: If true, only return entities with an authored
            edge from the current user (resolved from stored credentials).
        has_attachments: If true, only return Message entities that have
            at least one file or image attachment in metadata.attachments.
            Ignored for non-Message entity types.
        limit: Maximum number of results (default 50).
        order_by: Column to sort by descending (default "created_at").

    Returns:
        JSON array of matching entities. For Message entities with
        attachments, each result includes metadata.attachments — a JSON
        string that decodes to a list of {url, filename, content_type,
        width?, height?} objects. Discord attachment URLs are
        automatically refreshed before returning so they are valid at
        the time of the call.
    """
    str_filters: dict[str, str] = {k: str(v) for k, v in (filters or {}).items()}
    results = await query_by_filter(
        entity_type, filters=str_filters, limit=limit, order_by=order_by,
        since=since, authored_by_me=authored_by_me, has_attachments=has_attachments,
    )
    await _refresh_discord_attachments(results)
    return json.dumps(results, default=str)
