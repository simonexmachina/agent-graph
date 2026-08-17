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
from mcp.types import ToolAnnotations

from agentgraph.core.context import get_backend
from agentgraph.graph.operations import (
    get_entity_details,
    get_entity_edges,
    traverse_entity,
)
from agentgraph.graph.query import (
    query_by_filter,
    search_entities,
)
from agentgraph.perf import timed

logger = logging.getLogger(__name__)
MCP_INSTRUCTIONS = """AgentGraph is a local graph of selected messages, documents,
people, feeds, pages, and relationships. For source-backed questions, search broadly,
open promising entities for full content, traverse relevant relationships, and cite
source URLs or entity IDs. Search and query return bounded snippets; get returns the
full stored entity. Resolve or fetch stubs and stale context only when needed. Direct
fetch, polling, and ingest may contact configured source services and do not record
human attention in observed_at. Inspect connector or auth state only when availability
or freshness matters. Confirm destructive actions and Person merges with the user."""
mcp = FastMCP("AgentGraph", instructions=MCP_INSTRUCTIONS)


def _tool_annotations(
    title: str,
    *,
    read_only: bool,
    destructive: bool,
    idempotent: bool,
    open_world: bool,
) -> ToolAnnotations:
    return ToolAnnotations(
        title=title,
        readOnlyHint=read_only,
        destructiveHint=destructive,
        idempotentHint=idempotent,
        openWorldHint=open_world,
    )


def _truncate_content(entity: dict[str, Any], limit: int = 500) -> None:
    content = entity.get("content")
    if isinstance(content, str) and len(content) > limit:
        entity["content"] = content[:limit] + "…"
        entity["content_truncated"] = True
    else:
        entity["content_truncated"] = False


# ---------------------------------------------------------------------------
# list_connectors — connector discovery for agents
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_tool_annotations(
        "List AgentGraph connectors",
        read_only=True,
        destructive=False,
        idempotent=True,
        open_world=True,
    )
)
async def list_connectors_tool(verify: bool = False) -> str:
    """
    List all installed connectors and their capabilities.

    Use this when source availability, freshness, authentication, or valid
    platform values matter. Normal graph reads do not need to call it first.
    For query_by_filter_tool, scope a source with filters={"platform": "..."}.
    Set verify=true only when a live provider credential check is needed.

    Returns:
        JSON array of connector objects, each with:
          - source: platform name to pass as the platform= argument
          - description: what this connector ingests
          - auth_provider: shared auth provider key (e.g. "google"), or null
            for connectors that do not use credentials
          - auth_status: "ok" | "missing" | "invalid", or null when no auth is used
          - auth_detail: aggregate auth summary or error message; null if missing
          - auth_verified: true when credentials were live-checked with provider APIs
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
    result = await connector_status_items(all_connectors, get_backend(), verify=verify)
    return json.dumps(result)


@mcp.tool(
    annotations=_tool_annotations(
        "List AgentGraph authentication providers",
        read_only=True,
        destructive=False,
        idempotent=True,
        open_world=True,
    )
)
async def list_auth_providers_tool(verify: bool = False) -> str:
    """
    List credential-backed authentication providers and their current account/auth state.

    Connectors that require only configuration, or no setup at all, are omitted.
    Use list_connectors_tool to inspect all installed connectors.

    Returns:
        JSON array of auth provider objects, each with:
          - provider: auth provider key such as "google" or "slack"
          - description: provider summary
          - connectors: connector sources that use this provider
          - shared: true when multiple connectors use the same provider
          - auth_status: "ok" | "missing" | "invalid"
          - auth_detail: aggregate auth summary or error message; null if missing
          - auth_verified: true when credentials were live-checked with provider APIs
          - accounts: authenticated account rows with account_id, label, workspace_id,
            email, auth_method, auth_status, and auth_detail
    """
    from agentgraph.connectors.registry import bootstrap, get_all_connectors
    from agentgraph.connectors.status import auth_provider_status_items

    bootstrap()
    result = await auth_provider_status_items(get_all_connectors(), verify=verify)
    return json.dumps(result)


@mcp.tool(
    annotations=_tool_annotations(
        "Remove AgentGraph provider credentials",
        read_only=False,
        destructive=True,
        idempotent=True,
        open_world=False,
    )
)
async def remove_auth_provider_tool(provider: str, account_id: str | None = None) -> str:
    """
    Remove stored credentials for an authentication provider.

    This is the MCP equivalent of:
        agentgraph auth remove <provider> [--account <account-id>]

    Removing credentials stops authenticated connector operations such as
    background polling, but does not delete already indexed graph data.

    Args:
        provider: Auth provider key such as "google", "slack", or "discord".
        account_id: Optional account ID. When omitted, all credentials for the
            provider are removed.

    Returns:
        JSON object with provider, removed, and account_id when supplied.
    """
    from agentgraph.auth.credentials import remove_platform, remove_platform_account

    removed = (
        remove_platform_account(provider, account_id)
        if account_id is not None
        else remove_platform(provider)
    )
    result: dict[str, object] = {
        "provider": provider,
        "removed": removed,
    }
    if account_id is not None:
        result["account_id"] = account_id
    return json.dumps(result)


@mcp.tool(
    annotations=_tool_annotations(
        "Authenticate an AgentGraph provider",
        read_only=False,
        destructive=False,
        idempotent=False,
        open_world=True,
    )
)
async def authenticate_provider_tool(
    provider: str,
    args: list[str] | None = None,
    account_id: str | None = None,
    add: bool = False,
) -> str:
    """Authenticate a credential-backed provider through its connector-owned flow.

    This is the MCP equivalent of:
        agentgraph auth <provider> [--account <account-id>] [--add] [provider options]

    Slack accepts ``--method``, ``--client-id``, ``--xoxc-token``, and
    ``--d-cookie`` in ``args``. A Client ID implies OAuth; use the CLI for guided
    app setup.
    """
    import contextlib
    import io

    from agentgraph.connectors.registry import bootstrap, get_all_connectors
    from agentgraph.connectors.status import run_auth_provider_flow

    def _run() -> str:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            run_auth_provider_flow(
                get_all_connectors(),
                provider,
                account_id=account_id,
                add=add,
                args=args,
            )
        return output.getvalue()

    bootstrap()
    try:
        output = await asyncio.to_thread(_run)
    except ValueError as exc:
        return json.dumps({"provider": provider, "authenticated": False, "error": str(exc)})
    result: dict[str, object] = {"provider": provider, "authenticated": True}
    if output:
        result["output"] = output
    return json.dumps(result)


@mcp.tool(
    annotations=_tool_annotations(
        "Run an AgentGraph connector command",
        read_only=False,
        destructive=True,
        idempotent=False,
        open_world=True,
    )
)
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
            RSS add validates the supplied URLs as feeds before saving and
            queues an RSS poll after a successful change.
            RSS remove deletes the configured feed's local Folder and feed edges, while
            leaving indexed articles subject to their normal retention. It is available as:
            ["remove", "https://simonwillison.net/atom/everything/"].
            RSS OPML import is also available as:
            ["import-opml", "/path/to/feeds.opml", "--all"] or
            ["import-opml", "/path/to/feeds.opml", "--select", "1,3-5"].
            Gmail historical backfill is available as ["ingest"] or
            ["ingest", "--account", "<account-id>"]. There is no separate
            ingest_connector_tool; ingest is connector-owned.
            Connector-owned help is available as ["--help"].

    Returns:
        JSON object returned by the connector, or an error.
    """
    from agentgraph.connectors.registry import bootstrap, get_connector

    bootstrap()
    connector = get_connector(source)
    if connector is None:
        return json.dumps({"error": f"Unknown connector {source!r}"})
    if args in (["--help"], ["help"]):
        return json.dumps({"source": source, "help": type(connector).cli_help()})
    try:
        result = type(connector).run_cli_command(args)
        effects = type(connector).command_effects(args, result)
        if effects.delete_entities:
            from agentgraph.connectors.command_effects import execute_deletions

            result["deleted_entities"] = await execute_deletions(effects)
        if effects.poll:
            from agentgraph.server.sync import schedule_poll_connector

            result["poll"] = await schedule_poll_connector(connector)
        if effects.ingest:
            from agentgraph.server.sync import run_ingest

            account_ids = [effects.ingest_account_id] if effects.ingest_account_id else None
            asyncio.create_task(run_ingest(connector, account_ids=account_ids))
            result["ingest"] = {
                "source": connector.source,
                "status": "started",
                "account_id": effects.ingest_account_id,
            }
        return json.dumps(result, default=str)
    except (NotImplementedError, OSError, ValueError) as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool(
    annotations=_tool_annotations(
        "Install the AgentGraph skill",
        read_only=False,
        destructive=True,
        idempotent=True,
        open_world=False,
    )
)
async def install_skill_tool(
    skill: str = "AgentGraph", target: str = "user", force: bool = False, claude: bool = True
) -> str:
    """
    Install a bundled AgentGraph skill.

    This is the MCP equivalent of:
        agentgraph install-skill <skill> --target <user|project> [--no-claude] [--force]

    Args:
        skill: Bundled skill name. Defaults to "AgentGraph".
        target: "user" installs to ~/.agents/skills. "project" installs to
            ./.agents/skills relative to the MCP server process.
        claude: Link the skill into the corresponding Claude skills directory. Defaults to true.
        force: Overwrite an existing installed skill.

    Returns:
        JSON object with skill, target, source, destination, claude_destination,
        and overwritten,
        or an error.
    """
    from agentgraph.skills import SkillInstallError, install_skill

    if target not in ("user", "project"):
        return json.dumps({"error": "Target must be 'user' or 'project'"})

    try:
        result = install_skill(skill, target=target, force=force, claude=claude)
        return json.dumps(result.to_dict())
    except SkillInstallError as exc:
        return json.dumps({"error": str(exc)})


async def _enrich_results(results: list[dict[str, Any]]) -> None:
    """Let each owning connector apply result presentation fixes in-place."""
    from agentgraph.connectors.registry import bootstrap, get_connector

    bootstrap()
    by_platform: dict[str, list[dict[str, Any]]] = {}
    for entity in results:
        platform = entity.get("platform")
        if isinstance(platform, str):
            by_platform.setdefault(platform, []).append(entity)

    async def _enrich_one(platform: str, entities: list[dict[str, Any]]) -> None:
        connector = get_connector(platform)
        if connector is None:
            return
        try:
            with timed("mcp.enrich_results", platform=platform, count=len(entities)):
                await connector.enrich_results(entities)
        except Exception:
            logger.exception("Connector %s failed to enrich MCP results", platform)

    if by_platform:
        await asyncio.gather(
            *(_enrich_one(platform, entities) for platform, entities in by_platform.items())
        )


# ---------------------------------------------------------------------------
# search_entities — hybrid vector + full-text, RRF fused
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_tool_annotations(
        "Search AgentGraph entities",
        read_only=True,
        destructive=False,
        idempotent=True,
        open_world=True,
    )
)
async def search_entities_tool(
    query: str,
    entity_types: list[str] | None = None,
    platform: str | None = None,
    limit: int = 10,
    min_score: float = 0.03,
    refresh: bool = False,
) -> str:
    """
    Search the knowledge graph using a natural-language query.

    Combines semantic vector similarity and full-text search via
    Reciprocal Rank Fusion for high-quality results.

    IMPORTANT — attachments: chat photos, images, and uploaded files are
    stored as attachments on Message entities (in metadata.attachments).
    Gmail email attachments are represented as Gmail Document stubs referenced
    by the owning Email and can be downloaded with download_entity_tool.
    If the user asks about chat uploads, search Message entities or use
    query_by_filter_tool with has_attachments=True. If the user asks about
    Gmail attachments, inspect the Email's referenced Document stubs.

    Args:
        query: Natural-language search query.
        entity_types: Optional list of entity types to restrict results
            (e.g. ["Message", "Document", "Channel"]). To find chat images or
            attachments, pass ["Message"]. To find Gmail attachment stubs, pass
            ["Document"] and platform="gmail".
        platform: Optional platform name to scope the search to a single
            source (e.g. "slack", "discord", "gdocs", "gmail", "rss"). When
            omitted, all platforms are searched. Use this to avoid
            cross-platform noise when the user specifies a source.
        limit: Maximum number of results to return (default 10).
        min_score: Minimum relevance score threshold (0–1, default 0.03).
            Results below this score are suppressed as noise.
        refresh: If true, let connectors refresh or enrich connector-owned
            presentation metadata before returning. Defaults to false to keep
            search responsive.

    Returns:
        JSON array of matching entities with id, title, bounded content snippet,
        content_truncated, platform, and relevance score. Use get_entity_tool for
        full stored content. Connectors may refresh or enrich connector-owned
        metadata before results are returned.
    """
    results = await search_entities(
        query, entity_types=entity_types, limit=limit, min_score=min_score, platform=platform
    )
    for r in results:
        _truncate_content(r)
    if refresh:
        await _enrich_results(results)
    return json.dumps(results, default=str)


# ---------------------------------------------------------------------------
# get_entity — full entity by UUID
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_tool_annotations(
        "Get a full AgentGraph entity",
        read_only=False,
        destructive=False,
        idempotent=True,
        open_world=True,
    )
)
async def get_entity_tool(entity_id: str, resolve: bool = False) -> str:
    """
    Retrieve full details for a single existing entity.

    Args:
        entity_id: Entity UUID, unambiguous UUID prefix, platform ref, or indexed
            HTTP(S) URL.
        resolve: If true and the entity is a stub, fetch it through its owning
            connector before returning. Defaults to false.

    Returns:
        JSON object with all entity fields, or an error message if not found.
    """
    try:
        entity = await get_entity_details(entity_id, resolve=resolve)
        if entity is None:
            return json.dumps({"error": f"Entity {entity_id!r} not found"})
        return json.dumps(entity, default=str)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# get_edges — edges connected to an entity
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_tool_annotations(
        "List AgentGraph entity edges",
        read_only=True,
        destructive=False,
        idempotent=True,
        open_world=False,
    )
)
async def get_edges_tool(
    entity_id: str,
    edge_type: str | None = None,
    direction: str = "both",
) -> str:
    """
    List edges connected to an entity.

    Args:
        entity_id: Entity UUID, unambiguous UUID prefix, or platform ref.
        edge_type: Optional edge type filter (e.g. "authored", "posted_in",
            "replied_to", "mentions", "collaborated").
        direction: "in" (incoming), "out" (outgoing), or "both" (default).

    Returns:
        JSON array of edge objects including source/target references.
    """
    try:
        entity, edges = await get_entity_edges(
            entity_id,
            edge_type=edge_type,
            direction=direction,
        )
        if entity is None:
            return json.dumps({"error": f"Entity {entity_id!r} not found"})
        return json.dumps(edges, default=str)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# traverse_graph — BFS neighbourhood
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_tool_annotations(
        "Traverse the AgentGraph neighborhood",
        read_only=False,
        destructive=False,
        idempotent=True,
        open_world=True,
    )
)
async def traverse_graph_tool(
    entity_id: str,
    max_depth: int = 2,
    resolve: bool = False,
) -> str:
    """
    Traverse the knowledge graph from a starting entity using BFS.

    Useful for discovering the context around a message or document:
    who authored it, which channel it appeared in, what it references, etc.

    Args:
        entity_id: Entity UUID, unambiguous UUID prefix, or platform ref.
        max_depth: Maximum number of hops to traverse (default 2, max 4).
            A depth of 0 returns only the starting entity.
        resolve: If true, fetch stub nodes through their owning connectors and
            repeat the traversal before returning. Defaults to false.

    Returns:
        JSON object with "nodes" (entities) and "edges" lists.
    """
    try:
        depth = min(max(max_depth, 0), 4)
        entity, result = await traverse_entity(
            entity_id,
            max_depth=depth,
            resolve=resolve,
        )
        if entity is None:
            return json.dumps({"error": f"Entity {entity_id!r} not found"})

        # Trim content on nodes to keep response size manageable.
        for node in result.get("nodes", []):
            if node.get("content") and len(str(node["content"])) > 300:
                node["content"] = str(node["content"])[:300] + "…"
                node["content_truncated"] = True
            else:
                node["content_truncated"] = False
        return json.dumps(result, default=str)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# fetch_entity — trigger connector re-ingestion
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_tool_annotations(
        "Fetch an AgentGraph source resource",
        read_only=False,
        destructive=False,
        idempotent=True,
        open_world=True,
    )
)
async def fetch_entity_tool(platform: str, resource_id: str) -> str:
    """
    Trigger a connector fetch for a platform entity.

    Forces re-ingestion of a specific resource from its source platform,
    persisting updated content, people, and edges before returning.

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


@mcp.tool(
    annotations=_tool_annotations(
        "Refresh an AgentGraph entity",
        read_only=False,
        destructive=False,
        idempotent=True,
        open_world=True,
    )
)
async def fetch_entity_by_id_tool(entity_id: str) -> str:
    """
    Trigger a connector fetch for an entity by its internal UUID.

    Looks up the entity's platform and platform-specific ID, then forces
    re-ingestion from the source platform and persists the returned batch
    before returning.

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
# poll_connectors — trigger background connector polling
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_tool_annotations(
        "Poll AgentGraph connectors",
        read_only=False,
        destructive=False,
        idempotent=False,
        open_world=True,
    )
)
async def poll_connectors_tool(source: str | None = None) -> str:
    """
    Trigger a background poll for one connector or all polling connectors.

    This is the MCP equivalent of:
        agentgraph poll [<source>]

    Args:
        source: Optional connector source to poll. When omitted, all connectors
            with poll_interval configured are polled.

    Returns:
        JSON object with queued, already-running, and skipped connector sources,
        or an error if a requested connector source is not registered.
    """
    from agentgraph.connectors.registry import bootstrap, get_all_connectors, get_connector
    from agentgraph.server.sync import schedule_poll_connector

    bootstrap()
    if source is not None:
        connector = get_connector(source)
        if connector is None:
            return json.dumps({"error": f"No connector registered for source {source!r}"})
        connectors = [connector]
    else:
        connectors = get_all_connectors()

    polled: list[str] = []
    already_running: list[str] = []
    skipped: list[dict[str, str | None]] = []
    for connector in connectors:
        if connector.poll_interval is None:
            continue
        result = await schedule_poll_connector(connector)
        if result["status"] == "queued":
            polled.append(connector.source)
        elif result["status"] == "already_running":
            already_running.append(connector.source)
        else:
            skipped.append({"source": connector.source, "reason": result["reason"]})

    return json.dumps({"polled": polled, "already_running": already_running, "skipped": skipped})


# ---------------------------------------------------------------------------
# download_entity — authenticated source-file download
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_tool_annotations(
        "Download an AgentGraph source file",
        read_only=False,
        destructive=False,
        idempotent=True,
        open_world=True,
    )
)
async def download_entity_tool(entity_id: str, output_path: str | None = None) -> str:
    """
    Download an entity's source file using the connector's stored auth.

    Supports entity UUIDs, UUID prefixes, and platform refs such as
    "gdrive/file-id" or "gmail/document/attachment/<message-id>/<attachment-id>"
    when those resolve to a graph entity. The file is written to output_path
    when supplied, or to the MCP server's current directory using the source
    filename.

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
# bookmark_entity — protect an entity from expiration
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_tool_annotations(
        "Set AgentGraph bookmark protection",
        read_only=False,
        destructive=True,
        idempotent=True,
        open_world=True,
    )
)
async def bookmark_entity_tool(entity_id: str, bookmarked: bool = True) -> str:
    """
    Set or remove bookmark protection for an entity or URL.

    Supports entity UUIDs, UUID prefixes, and platform refs such as
    "gdrive/file-id" when those resolve to a graph entity. HTTP(S) URLs are
    fetched through an owning connector when possible when adding a bookmark,
    otherwise through the generic web connector.

    Args:
        entity_id: Entity UUID, UUID prefix, platform/entity_id reference, or URL.
        bookmarked: True to add bookmark protection; false to remove it.

    Returns:
        JSON object for the updated entity with its bookmark state, or an error
        message if the entity cannot be found.
    """
    from agentgraph.graph.bookmark import bookmark_target, set_entity_bookmark

    try:
        result = (
            await bookmark_target(entity_id)
            if bookmarked
            else await set_entity_bookmark(entity_id, False)
        )
        return json.dumps(result, default=str)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# delete_entity — remove an entity
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_tool_annotations(
        "Delete an AgentGraph entity",
        read_only=False,
        destructive=True,
        idempotent=False,
        open_world=False,
    )
)
async def delete_entity_tool(entity_id: str) -> str:
    """
    Delete an entity from the graph.

    Supports entity UUIDs, UUID prefixes, platform refs such as
    "gdrive/file-id", and HTTP(S) URLs when those resolve to a graph entity.
    Connected edges are deleted with the entity.

    Args:
        entity_id: Entity UUID, UUID prefix, platform/entity_id reference, or URL.

    Returns:
        JSON object with deleted=true and the deleted entity, or an error
        message if the entity cannot be found.
    """
    from agentgraph.graph.delete import delete_entity

    try:
        result = await delete_entity(entity_id)
        return json.dumps(result, default=str)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# unify_persons — manually merge duplicate Person entities
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_tool_annotations(
        "Unify duplicate AgentGraph people",
        read_only=False,
        destructive=True,
        idempotent=False,
        open_world=False,
    )
)
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


@mcp.tool(
    annotations=_tool_annotations(
        "Filter AgentGraph entities",
        read_only=True,
        destructive=False,
        idempotent=True,
        open_world=True,
    )
)
async def query_by_filter_tool(
    entity_type: str,
    filters: dict[str, Any] | None = None,
    since: str | None = None,
    authored_by_me: bool = False,
    has_attachments: bool = False,
    limit: int = 50,
    order_by: str = "created_at",
    refresh: bool = False,
) -> str:
    """
    Query entities by type with optional filters.

    Useful for listing all messages in a specific channel, all documents
    on a platform, activity within a time window, or content authored by
    the current user.

    Entity types and what they contain:
      - Message: chat messages from Discord, Slack, etc. This is
          where chat image and file uploads live — attachments are stored
          in metadata.attachments as a JSON array with fields: url,
          filename, content_type, width, height. To find images or
          uploaded files, query Message (not Document) and set
          has_attachments=True.
      - Document: text documents such as Google Docs, plus Gmail attachment
          stubs referenced by their owning Email. Gmail attachment Document
          stubs can be passed to download_entity_tool.
      - Spreadsheet: Google Sheets or Excel files.
      - Folder: a Google Drive folder containing other entities.
      - Channel: a chat channel or DM thread (Discord, Slack, etc.).
      - Email: an email thread (Gmail).
      - Person: a source identity or confirmed cross-source identity merge.

    Example — find images uploaded in the last 7 days:
        entity_type="Message", has_attachments=True, since="7d"

    Args:
        entity_type: Entity type to query. See above for what each type
            contains. Use "Message" to find chat uploads; use "Document" with
            filters={"platform": "gmail"} to find Gmail attachment stubs.
        filters: Optional dict of key=value filters. Known columns
            (platform, platform_entity_id) are applied as column filters;
            all other keys are matched against the metadata JSONB field.
        since: Optional time cutoff — ISO timestamp or relative duration
            like "12h", "30m", "2d". Only returns entities updated after
            this time.
        authored_by_me: If true, only return entities with an authored
            edge from the current user (resolved from stored credentials).
        has_attachments: If true, only return Message entities that have
            at least one chat file or image attachment in metadata.attachments.
            Ignored for non-Message entity types. Gmail attachments are
            Document stubs instead.
        limit: Maximum number of results (default 50).
        order_by: Date column to sort by descending: created_at, updated_at,
            source_created_at, source_updated_at, observed_at, or synced_at
            (default "created_at").
        refresh: If true, let connectors refresh or enrich connector-owned
            presentation metadata before returning. Defaults to false to keep
            queries responsive.

    Returns:
        JSON array of matching entities with bounded content and a
        content_truncated flag. For Message entities with
        attachments, each result includes metadata.attachments — a JSON
        string that decodes to a list of {url, filename, content_type,
        width?, height?} objects. Connectors may refresh or enrich
        connector-owned metadata before results are returned.
    """
    str_filters: dict[str, str] = {k: str(v) for k, v in (filters or {}).items()}
    results = await query_by_filter(
        entity_type,
        filters=str_filters,
        limit=limit,
        order_by=order_by,
        since=since,
        authored_by_me=authored_by_me,
        has_attachments=has_attachments,
    )
    for result in results:
        _truncate_content(result)
    if refresh:
        await _enrich_results(results)
    return json.dumps(results, default=str)
