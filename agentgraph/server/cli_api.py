"""CLI API router — raw entity/edge data endpoints for the agentgraph CLI."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/cli", tags=["cli"])

_WHITESPACE_RE = re.compile(r"\s+")


async def search_entities(
    query: str,
    entity_types: list[str] | None = None,
    limit: int = 10,
    min_score: float = 0.03,
    platform: str | None = None,
) -> list[dict[str, Any]]:
    from agentgraph.graph.query import search_entities as impl

    return await impl(query, entity_types, limit, min_score, platform)


async def get_entity(entity_id: str) -> dict[str, Any] | None:
    from agentgraph.graph.query import get_entity as impl

    return await impl(entity_id)


async def get_entity_by_url(url: str) -> dict[str, Any] | None:
    from agentgraph.graph.query import get_entity_by_url as impl

    return await impl(url)


async def get_edges(
    entity_id: str,
    edge_type: str | None = None,
    direction: str = "both",
) -> list[dict[str, Any]]:
    from agentgraph.graph.query import get_edges as impl

    return await impl(entity_id, edge_type=edge_type, direction=direction)


async def traverse_graph(entity_id: str, max_depth: int = 2) -> dict[str, Any]:
    from agentgraph.graph.query import traverse_graph as impl

    return await impl(entity_id, max_depth=max_depth)


async def get_edges_for_entities(entity_ids: list[str]) -> list[dict[str, Any]]:
    from agentgraph.graph.query import get_edges_for_entities as impl

    return await impl(entity_ids)


async def get_entities_by_ids(entity_ids: list[str]) -> list[dict[str, Any]]:
    from agentgraph.graph.query import get_entities_by_ids as impl

    return await impl(entity_ids)


async def list_entities(
    entity_types: list[str] | None = None,
    platform: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    from agentgraph.graph.query import list_entities as impl

    return await impl(entity_types, platform, since, limit)


async def list_entities_page(
    entity_types: list[str] | None = None,
    platform: str | None = None,
    since: str | None = None,
    limit: int = 50,
    offset: int = 0,
    order_by: str = "last_accessed",
    order_dir: str = "desc",
) -> tuple[list[dict[str, Any]], int]:
    from agentgraph.graph.query import list_entities_page as impl

    return await impl(entity_types, platform, since, limit, offset, order_by, order_dir)


async def query_by_filter(
    entity_type: str,
    filters: dict[str, str],
    limit: int = 50,
    order_by: str = "last_accessed",
    since: str | None = None,
    authored_by_me: bool = False,
    has_attachments: bool = False,
) -> list[dict[str, Any]]:
    from agentgraph.graph.query import query_by_filter as impl

    return await impl(
        entity_type,
        filters=filters,
        limit=limit,
        order_by=order_by,
        since=since,
        authored_by_me=authored_by_me,
        has_attachments=has_attachments,
    )


def _normalise_display_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = _WHITESPACE_RE.sub(" ", value).strip()
    return text or None


def _entity_display_name(entity: dict[str, Any]) -> str:
    metadata = entity.get("metadata")
    metadata_dict = metadata if isinstance(metadata, dict) else {}
    candidates = (
        entity.get("title"),
        metadata_dict.get("display_name"),
        metadata_dict.get("canonical_email"),
        entity.get("content"),
        entity.get("platform_entity_id"),
        entity.get("id"),
    )
    for candidate in candidates:
        text = _normalise_display_text(candidate)
        if text:
            return text
    return "Untitled"


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(limit - 1, 0)].rstrip() + "…"


def _entity_viewer_label(entity: dict[str, Any]) -> str:
    display_name = _entity_display_name(entity)
    if entity.get("entity_type") == "Message":
        return _truncate_text(display_name, 80)
    return display_name


def _with_display_name(entity: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(entity)
    enriched["display_name"] = _entity_display_name(entity)
    enriched["viewer_label"] = _entity_viewer_label(entity)
    return enriched


def _with_display_names(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_with_display_name(entity) for entity in entities]


def _summarize_entity(entity: dict[str, Any], *, content_limit: int = 500) -> dict[str, Any]:
    summarized = dict(entity)
    content = summarized.get("content")
    if isinstance(content, str) and len(content) > content_limit:
        summarized["content"] = _truncate_text(content, content_limit)
        summarized["content_truncated"] = True
    else:
        summarized["content_truncated"] = False
    return summarized


def _summarize_entities(
    entities: list[dict[str, Any]],
    *,
    content_limit: int = 500,
) -> list[dict[str, Any]]:
    return [_summarize_entity(entity, content_limit=content_limit) for entity in entities]


@router.get("/meta")
async def cli_meta() -> dict[str, Any]:
    """Return registered connector sources, URL patterns, and known entity types."""
    from agentgraph.config import get_settings
    from agentgraph.connectors.base import ENTITY_TYPES
    from agentgraph.connectors.registry import get_all_connectors

    connectors = get_all_connectors()
    seen_patterns: list[str] = []
    seen_set: set[str] = set()
    for c in connectors:
        for p in c.url_patterns:
            if p not in seen_set:
                seen_patterns.append(p)
                seen_set.add(p)

    return {
        "entity_types": list(ENTITY_TYPES),
        "platforms": sorted({c.source for c in connectors}),
        "url_patterns": seen_patterns,
        "dwell_threshold_ms": get_settings().dwell_threshold_seconds * 1000,
    }


@router.get("/search")
async def cli_search(
    q: str,
    entity_type: list[str] = Query(default=[]),
    limit: int = Query(default=10, ge=1, le=200),
    min_score: float = Query(default=0.03, ge=0.0, le=1.0),
    platform: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    results = await search_entities(
        q, entity_types=entity_type or None, limit=limit, min_score=min_score, platform=platform
    )
    return _summarize_entities(results)


@router.get("/entity/{entity_id:path}")
async def cli_get_entity(entity_id: str) -> dict[str, Any]:
    entity = await get_entity(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return _with_display_name(entity)


@router.get("/entity-by-url")
async def cli_get_entity_by_url(url: str = Query(...)) -> dict[str, Any]:
    entity = await get_entity_by_url(url)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return _with_display_name(entity)


@router.get("/edges/{entity_id:path}")
async def cli_get_edges(
    entity_id: str,
    edge_type: str | None = Query(default=None),
    direction: str = Query(default="both"),
) -> list[dict[str, Any]]:
    entity = await get_entity(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return await get_edges(entity["id"], edge_type=edge_type, direction=direction)


@router.get("/traverse/{entity_id:path}")
async def cli_traverse(
    entity_id: str,
    depth: int = Query(default=2, ge=1, le=4),
) -> dict[str, Any]:
    entity = await get_entity(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return await traverse_graph(entity["id"], max_depth=depth)


_VIEWER_ORDER_FIELDS = {
    "created_at",
    "display_name",
    "entity_type",
    "platform",
    "updated_at",
    "last_accessed",
    "synced_at",
}


def _viewer_sort_value(node: dict[str, Any], order_by: str) -> str:
    if order_by == "display_name":
        return _entity_display_name(node).casefold()
    value = node.get(order_by)
    return value.casefold() if isinstance(value, str) else ""


def _page_entities(
    nodes: list[dict[str, Any]], page: int, page_size: int, order_by: str, order_dir: str
) -> tuple[list[dict[str, Any]], int]:
    reverse = order_dir.lower() != "asc"
    if order_by in _VIEWER_ORDER_FIELDS:
        nodes = sorted(nodes, key=lambda node: _viewer_sort_value(node, order_by), reverse=reverse)
    total = len(nodes)
    start = (page - 1) * page_size
    return nodes[start : start + page_size], total


async def _resolve_viewer_node_set(
    search: str | None,
    entity_type: list[str],
    platform: str | None,
    since: str | None,
    node_id: str | None,
    depth: int,
    limit: int,
    *,
    page: int | None = None,
    page_size: int | None = None,
    order_by: str = "last_accessed",
    order_dir: str = "desc",
) -> tuple[list[dict[str, Any]], int, bool]:
    """Resolve the filtered viewer node set; traversal edges are only used for pruning."""
    # --- Phase 1: neighbourhood (only when node_id given) ---
    focal: dict[str, Any] | None = None
    neighbourhood_ids: set[str] | None = None
    traverse_edges: list[dict[str, Any]] = []

    if node_id is not None:
        focal = await get_entity(node_id)
        if focal is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        tresult = await traverse_graph(focal["id"], max_depth=depth)
        neighbourhood_ids = {n["id"] for n in tresult["nodes"]}
        traverse_edges = tresult["edges"]

    # --- Phase 2: candidate nodes ---
    if search:
        search_limit = limit + 1 if neighbourhood_ids is None else max(limit + 1, 500)
        nodes = await search_entities(search, entity_types=entity_type or None, limit=search_limit)
        if neighbourhood_ids is not None:
            nodes = [n for n in nodes if n["id"] in neighbourhood_ids]
    elif neighbourhood_ids is not None:
        nodes = [n for n in tresult["nodes"]]  # type: ignore[possibly-undefined]
        if entity_type:
            allowed_types = set(entity_type)
            nodes = [n for n in nodes if n["entity_type"] in allowed_types]
    elif page is not None and page_size is not None:
        offset = (page - 1) * page_size
        nodes, total = await list_entities_page(
            entity_types=entity_type or None,
            platform=platform,
            since=since,
            limit=min(page_size, max(limit - offset, 0)),
            offset=offset,
            order_by=order_by,
            order_dir=order_dir,
        )
        return nodes, min(total, limit), total > limit
    else:
        nodes = await list_entities(
            entity_types=entity_type or None,
            platform=platform,
            since=since,
            limit=limit + 1,
        )

    # Apply platform / since on search and neighbourhood paths (list_entities handles them natively)
    if platform and (search or neighbourhood_ids is not None):
        nodes = [n for n in nodes if n.get("platform") == platform]
    if since and (search or neighbourhood_ids is not None):
        nodes = [n for n in nodes if (n.get("updated_at") or "") >= since]

    has_more = len(nodes) > limit
    nodes = nodes[:limit]

    # Focal node is always shown, even when it doesn't match the active filters
    if focal is not None and focal["id"] not in {n["id"] for n in nodes}:
        nodes = [focal] + nodes

    visible_ids = {n["id"] for n in nodes}

    # --- Phase 3: edges + prune / adjacent expansion ---
    if neighbourhood_ids is not None:
        edges = [
            e for e in traverse_edges
            if e["source_entity_id"] in visible_ids and e["target_entity_id"] in visible_ids
        ]
        # BFS from focal through filtered edges; removes nodes only reachable via hidden types
        reachable: set[str] = set()
        adjacency: dict[str, set[str]] = {}
        for e in edges:
            adjacency.setdefault(e["source_entity_id"], set()).add(e["target_entity_id"])
            adjacency.setdefault(e["target_entity_id"], set()).add(e["source_entity_id"])
        queue = [focal["id"]]  # type: ignore[possibly-undefined]
        while queue:
            nid = queue.pop()
            if nid in reachable:
                continue
            reachable.add(nid)
            queue.extend(adjacency.get(nid, set()) - reachable)
        nodes = [n for n in nodes if n["id"] in reachable]
        visible_ids = {n["id"] for n in nodes}
        edges = [
            e for e in edges
            if e["source_entity_id"] in visible_ids and e["target_entity_id"] in visible_ids
        ]
    else:
        edges = await get_edges_for_entities(list(visible_ids))
        # When search + entity_type active, pull in adjacent nodes of those types so that
        # e.g. searching for a Thread also surfaces the Persons connected to it.
        if search and entity_type:
            allowed = set(entity_type)
            neighbour_ids = {
                eid
                for e in edges
                for eid in (e["source_entity_id"], e["target_entity_id"])
                if eid not in visible_ids
            }
            if neighbour_ids:
                neighbours = await get_entities_by_ids(list(neighbour_ids))
                neighbours = [n for n in neighbours if n["entity_type"] in allowed]
                has_more = has_more or len(nodes) + len(neighbours) > limit
                nodes = (nodes + neighbours)[:limit]

    if page is not None and page_size is not None:
        nodes, total = _page_entities(nodes, page, page_size, order_by, order_dir)
    else:
        total = len(nodes)
    return nodes, total, has_more


async def _viewer_edges(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    visible_ids = {node["id"] for node in nodes}
    if not visible_ids:
        return []
    edges = await get_edges_for_entities(list(visible_ids))
    return [
        edge for edge in edges
        if edge["source_entity_id"] in visible_ids and edge["target_entity_id"] in visible_ids
    ]


@router.get("/browse/nodes")
async def cli_browse_nodes(
    search: str | None = Query(default=None),
    entity_type: list[str] = Query(default=[]),
    platform: str | None = Query(default=None),
    since: str | None = Query(default=None),
    node_id: str | None = Query(default=None),
    depth: int = Query(default=2, ge=1, le=4),
    limit: int = Query(default=50, ge=1, le=1000),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=1000),
    sort: str = Query(default="last_accessed"),
    sort_dir: str = Query(default="desc"),
) -> dict[str, Any]:
    """Return one ordered page from the viewer node set."""
    nodes, total, has_more = await _resolve_viewer_node_set(
        search, entity_type, platform, since, node_id, depth, limit,
        page=page, page_size=size, order_by=sort, order_dir=sort_dir,
    )
    return {
        "data": _with_display_names(_summarize_entities(nodes, content_limit=300)),
        "last_page": max(1, (total + size - 1) // size),
        "total": total,
        "has_more": has_more,
    }


@router.get("/browse/edges")
async def cli_browse_edges(node_ids: str = Query(default="")) -> dict[str, Any]:
    """Return edges whose endpoints are both in comma-separated node_ids."""
    ids = list(dict.fromkeys(node_id.strip() for node_id in node_ids.split(",") if node_id.strip()))
    if len(ids) > 1000:
        raise HTTPException(status_code=422, detail="At most 1000 node_ids are allowed")
    edges = await get_edges_for_entities(ids)
    visible_ids = set(ids)
    return {
        "edges": [
            edge for edge in edges
            if edge["source_entity_id"] in visible_ids and edge["target_entity_id"] in visible_ids
        ]
    }


@router.get("/browse")
async def cli_browse(
    search: str | None = Query(default=None),
    entity_type: list[str] = Query(default=[]),
    platform: str | None = Query(default=None),
    since: str | None = Query(default=None),
    node_id: str | None = Query(default=None),
    depth: int = Query(default=2, ge=1, le=4),
    limit: int = Query(default=50, ge=1, le=1000),
) -> dict[str, Any]:
    """Compatibility graph response, composed from the shared node-set resolver."""
    nodes, _, _ = await _resolve_viewer_node_set(
        search, entity_type, platform, since, node_id, depth, limit
    )
    return {
        "nodes": _with_display_names(_summarize_entities(nodes, content_limit=300)),
        "edges": await _viewer_edges(nodes),
    }


@router.get("/query")
async def cli_query(
    entity_type: str,
    limit: int = Query(default=50, ge=1, le=500),
    order_by: str = Query(default="last_accessed"),
    since: str | None = Query(default=None),
    mine: bool = Query(default=False),
    has_attachments: bool = Query(default=False),
    filter: list[str] = Query(default=[]),
) -> list[dict[str, Any]]:
    """Query entities by type with optional filters (key=value pairs)."""
    filters: dict[str, str] = {}
    for f in filter:
        if "=" in f:
            k, _, v = f.partition("=")
            filters[k.strip()] = v.strip()
    results = await query_by_filter(
        entity_type,
        filters=filters,
        limit=limit,
        order_by=order_by,
        since=since,
        authored_by_me=mine,
        has_attachments=has_attachments,
    )
    return _summarize_entities(results)


@router.post("/fetch")
async def cli_fetch(
    platform: str = Query(...),
    resource_id: str = Query(...),
) -> dict[str, Any]:
    """Trigger a connector fetch for a platform entity."""
    from agentgraph.graph.fetch import fetch_entity

    try:
        return await fetch_entity(platform, resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/download")
async def cli_download(
    entity_id: str = Query(...),
    output_path: str | None = Query(default=None),
) -> dict[str, Any]:
    """Download an entity's source file using connector auth."""
    from agentgraph.graph.download import download_entity

    try:
        return await download_entity(entity_id, output_path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/bookmark")
async def cli_bookmark(
    target: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    bookmarked: bool = Query(default=True),
) -> dict[str, Any]:
    """Set bookmark state for an entity or URL."""
    from agentgraph.graph.bookmark import bookmark_target, set_entity_bookmark

    try:
        bookmark_target_value = target or entity_id
        if bookmark_target_value is None:
            raise ValueError("Missing bookmark target")
        if not bookmarked:
            return await set_entity_bookmark(bookmark_target_value, False)
        return await bookmark_target(bookmark_target_value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/delete")
async def cli_delete(
    target: str = Query(...),
) -> dict[str, Any]:
    """Delete an entity from the graph."""
    from agentgraph.graph.delete import delete_entity

    try:
        return await delete_entity(target)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/unify-persons")
async def cli_unify_persons(
    primary: str = Query(...),
    duplicate: list[str] = Query(...),
) -> dict[str, Any]:
    """Merge duplicate Person entities into a chosen primary Person."""
    from agentgraph.graph.person import unify_persons

    try:
        return await unify_persons(primary, duplicate)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/poll")
async def cli_poll(
    source: str | None = Query(default=None),
) -> dict[str, Any]:
    """Trigger a background poll for one connector (by source) or all connectors."""
    from agentgraph.connectors.registry import get_all_connectors, get_connector
    from agentgraph.server.sync import schedule_poll_connector

    if source is not None:
        connector = get_connector(source)
        if connector is None:
            raise HTTPException(status_code=404, detail=f"No connector registered for source '{source}'")
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

    return {"polled": polled, "already_running": already_running, "skipped": skipped}


@router.post("/ingest")
async def cli_ingest(
    source: str = Query(...),
) -> dict[str, Any]:
    """Kick off a background bulk ingest for a connector and return immediately."""
    from agentgraph.connectors.registry import get_connector
    from agentgraph.server.sync import run_ingest

    connector = get_connector(source)
    if connector is None:
        raise HTTPException(status_code=404, detail=f"No connector registered for source '{source}'")

    asyncio.create_task(run_ingest(connector))
    return {"source": source, "status": "started"}


@router.post("/fetch-entity")
async def cli_fetch_entity(
    entity_id: str = Query(...),
) -> dict[str, Any]:
    """Trigger a connector fetch for an entity by its internal UUID."""
    from agentgraph.graph.fetch import fetch_entity_by_id

    try:
        return await fetch_entity_by_id(entity_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
