"""CLI API router — raw entity/edge data endpoints for the agentgraph CLI."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from agentgraph.graph.query import (
    get_edges,
    get_edges_for_entities,
    get_entity,
    list_entities,
    query_by_filter,
    search_entities,
    traverse_graph,
)

router = APIRouter(prefix="/api/cli", tags=["cli"])


@router.get("/meta")
async def cli_meta() -> dict[str, Any]:
    """Return registered connector sources and known entity types."""
    from agentgraph.connectors.base import ENTITY_TYPES
    from agentgraph.connectors.registry import get_all_connectors

    connectors = get_all_connectors()
    return {
        "entity_types": list(ENTITY_TYPES),
        "platforms": sorted({c.source for c in connectors}),
    }


@router.get("/search")
async def cli_search(
    q: str,
    entity_type: list[str] = Query(default=[]),
    limit: int = Query(default=10, ge=1, le=200),
    min_score: float = Query(default=0.03, ge=0.0, le=1.0),
    platform: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    return await search_entities(
        q, entity_types=entity_type or None, limit=limit, min_score=min_score, platform=platform
    )


@router.get("/entity/{entity_id:path}")
async def cli_get_entity(entity_id: str) -> dict[str, Any]:
    entity = await get_entity(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


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
    """Return graph nodes and edges for the viewer. All active filters are intersected."""
    neighbourhood_ids: set[str] | None = None
    traverse_edges: list[dict[str, Any]] = []

    if node_id is not None:
        focal = await get_entity(node_id)
        if focal is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        result = await traverse_graph(focal["id"], max_depth=depth)
        neighbourhood_ids = {n["id"] for n in result["nodes"]}
        traverse_edges = result["edges"]

    if search:
        # Use a high limit when intersecting with neighbourhood so we don't miss matches
        search_limit = limit if neighbourhood_ids is None else max(limit, 500)
        nodes = await search_entities(search, entity_types=entity_type or None, limit=search_limit)
        if neighbourhood_ids is not None:
            nodes = [n for n in nodes if n["id"] in neighbourhood_ids]
    elif neighbourhood_ids is not None:
        nodes = [n for n in result["nodes"]]  # type: ignore[possibly-undefined]
        if entity_type:
            allowed = set(entity_type)
            nodes = [n for n in nodes if n["entity_type"] in allowed]
    else:
        nodes = await list_entities(
            entity_types=entity_type or None,
            platform=platform,
            since=since,
            limit=limit,
        )

    # Apply platform / since filters on all paths that don't already handle them
    if platform and (search or neighbourhood_ids is not None):
        nodes = [n for n in nodes if n.get("platform") == platform]
    if since and (search or neighbourhood_ids is not None):
        nodes = [n for n in nodes if (n.get("updated_at") or "") >= since]

    nodes = nodes[:limit]
    visible_ids = {n["id"] for n in nodes}

    if neighbourhood_ids is not None:
        # Build edges between visible nodes only
        edges = [
            e for e in traverse_edges
            if e["source_entity_id"] in visible_ids and e["target_entity_id"] in visible_ids
        ]
        # When entity_type filters hide intermediate nodes, some visible nodes may no longer
        # have a path back to the focal node through the visible edge set. Remove them.
        if focal["id"] in visible_ids:  # type: ignore[possibly-undefined]
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
            edges = [e for e in edges if e["source_entity_id"] in visible_ids and e["target_entity_id"] in visible_ids]
    else:
        edges = await get_edges_for_entities(list(visible_ids))

    return {"nodes": nodes, "edges": edges}


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
    return await query_by_filter(
        entity_type,
        filters=filters,
        limit=limit,
        order_by=order_by,
        since=since,
        authored_by_me=mine,
        has_attachments=has_attachments,
    )


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


@router.post("/poll")
async def cli_poll(
    source: str | None = Query(default=None),
) -> dict[str, Any]:
    """Trigger a background poll for one connector (by source) or all connectors."""
    from agentgraph.connectors.registry import get_all_connectors
    from agentgraph.server.sync import _poll_connector

    connectors = get_all_connectors()
    if source is not None:
        connectors = [c for c in connectors if c.source == source]
        if not connectors:
            raise HTTPException(status_code=404, detail=f"No connector registered for source '{source}'")

    polled: list[str] = []
    for connector in connectors:
        if connector.poll_interval is None:
            continue
        asyncio.create_task(_poll_connector(connector))
        polled.append(connector.source)

    return {"polled": polled}


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
