"""HTTP data endpoints retained for the local graph viewer and extension."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/cli", tags=["cli"])

_WHITESPACE_RE = re.compile(r"\s+")
_DYNAMIC_PATTERN_TIMEOUT_SECONDS = 2.0
logger = logging.getLogger(__name__)


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
    order_by: str | None = "observed_at",
    order_dir: str = "desc",
) -> tuple[list[dict[str, Any]], int]:
    from agentgraph.graph.query import list_entities_page as impl

    return await impl(entity_types, platform, since, limit, offset, order_by, order_dir)


def parse_since(since: str) -> datetime:
    from agentgraph.graph.query import parse_since as impl

    return impl(since)


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


def _summarize_entities(
    entities: list[dict[str, Any]],
    *,
    content_limit: int = 500,
) -> list[dict[str, Any]]:
    from agentgraph.graph.operations import summarize_entities

    return summarize_entities(entities, content_limit=content_limit)


@router.get("/meta")
async def cli_meta(include_dynamic_url_patterns: bool = True) -> dict[str, Any]:
    """Return registered connector sources, URL patterns, and known entity types."""
    from agentgraph.config import get_settings
    from agentgraph.connectors.base import ENTITY_TYPES
    from agentgraph.connectors.registry import get_all_connectors

    connectors = get_all_connectors()
    seen_patterns: list[str] = []
    seen_set: set[str] = set()
    for c in connectors:
        if include_dynamic_url_patterns:
            try:
                patterns = await asyncio.wait_for(
                    c.observation_url_patterns(), timeout=_DYNAMIC_PATTERN_TIMEOUT_SECONDS
                )
            except TimeoutError:
                logger.warning(
                    "Timed out loading observation URL patterns for connector %s",
                    c.source,
                )
                continue
        else:
            patterns = c.url_patterns
        for p in patterns:
            if p not in seen_set:
                seen_patterns.append(p)
                seen_set.add(p)

    return {
        "entity_types": list(ENTITY_TYPES),
        "platforms": sorted({c.source for c in connectors}),
        "url_patterns": seen_patterns,
        "observation_threshold_ms": get_settings().observation_threshold_seconds * 1000,
    }


@router.get("/entity/{entity_id:path}")
async def cli_get_entity(entity_id: str) -> dict[str, Any]:
    from agentgraph.graph.operations import get_entity_details

    entity = await get_entity_details(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return _with_display_name(entity)


@router.get("/edges/{entity_id:path}")
async def cli_get_edges(
    entity_id: str,
    edge_type: str | None = Query(default=None),
    direction: str = Query(default="both"),
) -> list[dict[str, Any]]:
    from agentgraph.graph.operations import get_entity_edges

    entity, edges = await get_entity_edges(
        entity_id,
        edge_type=edge_type,
        direction=direction,
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return edges


_VIEWER_ORDER_FIELDS = {
    "created_at",
    "display_name",
    "entity_type",
    "platform",
    "source_created_at",
    "source_updated_at",
    "updated_at",
    "observed_at",
    "synced_at",
}


def _viewer_sort_value(node: dict[str, Any], order_by: str) -> str:
    if order_by == "display_name":
        return _entity_display_name(node).casefold()
    value = node.get(order_by)
    return value.casefold() if isinstance(value, str) else ""


def _viewer_updated_at_on_or_after(node: dict[str, Any], cutoff: datetime) -> bool:
    updated_at = node.get("updated_at")
    if not isinstance(updated_at, str):
        return False
    try:
        updated_at_dt = datetime.fromisoformat(updated_at)
    except ValueError:
        return False
    if updated_at_dt.tzinfo is None:
        updated_at_dt = updated_at_dt.replace(tzinfo=UTC)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=UTC)
    return updated_at_dt >= cutoff


def _page_entities(
    nodes: list[dict[str, Any]],
    page: int,
    page_size: int,
    order_by: str | None,
    order_dir: str,
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
    order_by: str = "observed_at",
    order_dir: str = "desc",
    ordered: bool = True,
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
        # The viewer needs every lexical match up to its active limit so it can
        # reliably expose the More control. Hybrid RRF scores naturally fall
        # below the default cutoff for lower-ranked exact text matches.
        nodes = await search_entities(
            search,
            entity_types=entity_type or None,
            limit=search_limit,
            min_score=0.0,
        )
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
            order_by=order_by if ordered else None,
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
        cutoff = parse_since(since)
        nodes = [n for n in nodes if _viewer_updated_at_on_or_after(n, cutoff)]

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
        # e.g. searching for an Email also surfaces the Persons connected to it.
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
        nodes, total = _page_entities(
            nodes,
            page,
            page_size,
            order_by if ordered else None,
            order_dir,
        )
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


async def cli_browse(
    search: str | None = None,
    entity_type: list[str] | None = None,
    platform: str | None = None,
    since: str | None = None,
    node_id: str | None = None,
    depth: int = 2,
    limit: int = 50,
) -> dict[str, Any]:
    """Compose the legacy graph response for viewer resolver tests, without an HTTP route."""
    nodes, _, _ = await _resolve_viewer_node_set(
        search,
        entity_type or [],
        platform,
        since,
        node_id,
        depth,
        limit,
    )
    return {
        "nodes": _with_display_names(_summarize_entities(nodes, content_limit=300)),
        "edges": await _viewer_edges(nodes),
    }


@router.get("/browse/nodes")
async def cli_browse_nodes(
    search: str | None = Query(default=None),
    entity_type: list[str] = Query(default=[]),
    platform: str | None = Query(default=None),
    since: str | None = Query(default=None),
    node_id: str | None = Query(default=None),
    depth: int = Query(default=2, ge=0, le=4),
    limit: int = Query(default=50, ge=1, le=1000),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=1000),
    sort: str = Query(default="observed_at"),
    sort_dir: str = Query(default="desc"),
    ordered: bool = Query(default=True),
) -> dict[str, Any]:
    """Return one viewer node page, optionally omitting ordering for graph layout."""
    nodes, total, has_more = await _resolve_viewer_node_set(
        search, entity_type, platform, since, node_id, depth, limit,
        page=page,
        page_size=size,
        order_by=sort,
        order_dir=sort_dir,
        ordered=ordered,
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
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
