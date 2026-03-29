"""CLI API router — raw entity/edge data endpoints for the agentgraph CLI."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

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


@router.get("/search")
async def cli_search(
    q: str,
    entity_type: list[str] = Query(default=[]),
    limit: int = Query(default=10, ge=1, le=200),
    min_score: float = Query(default=0.03, ge=0.0, le=1.0),
) -> list[dict[str, Any]]:
    return await search_entities(q, entity_types=entity_type or None, limit=limit, min_score=min_score)


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
    """Return graph nodes and edges for the viewer. Supports traverse, search, and browse modes."""
    if node_id is not None:
        entity = await get_entity(node_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        result = await traverse_graph(entity["id"], max_depth=depth)
        nodes = result["nodes"]
        edges = result["edges"]
        if entity_type:
            allowed = set(entity_type)
            nodes = [e for e in nodes if e["entity_type"] in allowed]
        return {"nodes": nodes, "edges": edges}

    if search:
        nodes = await search_entities(search, entity_types=entity_type or None, limit=limit)
    else:
        nodes = await list_entities(
            entity_types=entity_type or None,
            platform=platform,
            since=since,
            limit=limit,
        )

    entity_ids = [e["id"] for e in nodes]
    edges = await get_edges_for_entities(entity_ids)
    return {"nodes": nodes, "edges": edges}


@router.get("/query")
async def cli_query(
    entity_type: str,
    limit: int = Query(default=50, ge=1, le=500),
    order_by: str = Query(default="last_accessed"),
    since: str | None = Query(default=None),
    mine: bool = Query(default=False),
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
