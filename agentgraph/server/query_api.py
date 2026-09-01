"""HTTP surface backing the CLI's ``server`` query transport.

Deliberately separate from ``cli_api``: those routes serve the graph viewer and add
viewer-only fields such as ``display_name``. These routes return exactly what the
equivalent in-process call returns, so ``agentgraph <cmd> --json`` produces identical
output whichever transport resolved it. Tests in ``tests/test_query_parity.py`` hold
that line.

Absent entities are reported as ``null`` with a 200 rather than a 404, mirroring the
in-process functions that return ``None``; only genuine failures raise.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

router = APIRouter(prefix="/api/query", tags=["query"])


def _bad_request(exc: ValueError) -> HTTPException:
    """Surface a ValueError so the client can re-raise it with the same message."""
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/health")
async def query_health() -> dict[str, str]:
    """Capability probe. Clients use this to detect a server predating these routes,
    so `auto` can fall back to in-process instead of failing on a 404."""
    return {"status": "ok"}


@router.get("/search")
async def query_search(
    query: str,
    entity_types: list[str] | None = Query(default=None),
    limit: int = Query(default=10),
    min_score: float = Query(default=0.03),
    platform: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    from agentgraph.graph.operations import summarize_entities
    from agentgraph.graph.query import search_entities

    results = await search_entities(
        query,
        entity_types=entity_types or None,
        limit=limit,
        min_score=min_score,
        platform=platform,
    )
    return summarize_entities(results)


@router.get("/entity")
async def query_entity(
    entity_id: str,
    resolve: bool = Query(default=False),
) -> dict[str, Any] | None:
    from agentgraph.graph.operations import get_entity_details

    return await get_entity_details(entity_id, resolve=resolve)


@router.get("/edges")
async def query_edges(
    entity_id: str,
    edge_type: str | None = Query(default=None),
    direction: str = Query(default="both"),
) -> dict[str, Any]:
    """Return the resolved entity alongside its edges; the CLI needs both."""
    from agentgraph.graph.operations import get_entity_edges

    entity, edges = await get_entity_edges(
        entity_id,
        edge_type=edge_type,
        direction=direction,
    )
    return {"entity": entity, "edges": edges}


@router.get("/traverse")
async def query_traverse(
    entity_id: str,
    max_depth: int = Query(default=2),
    resolve: bool = Query(default=False),
) -> dict[str, Any]:
    from agentgraph.graph.operations import traverse_entity

    entity, result = await traverse_entity(entity_id, max_depth=max_depth, resolve=resolve)
    return {"entity": entity, "result": result}


@router.post("/filter")
async def query_filter(
    entity_type: str,
    filters: dict[str, str] = Body(default_factory=dict),
    limit: int = Query(default=50),
    order_by: str = Query(default="observed_at"),
    since: str | None = Query(default=None),
    authored_by_me: bool = Query(default=False),
    has_attachments: bool = Query(default=False),
) -> list[dict[str, Any]]:
    """Filter query. POST because ``filters`` is an open-ended field/value mapping."""
    from agentgraph.graph.operations import summarize_entities
    from agentgraph.graph.query import query_by_filter

    try:
        results = await query_by_filter(
            entity_type,
            filters=filters,
            limit=limit,
            order_by=order_by,
            since=since,
            authored_by_me=authored_by_me,
            has_attachments=has_attachments,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return summarize_entities(results)


@router.post("/fetch")
async def query_fetch(platform: str, resource_id: str) -> dict[str, Any]:
    from agentgraph.graph.fetch import fetch_entity

    try:
        return await fetch_entity(platform, resource_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/fetch-entity")
async def query_fetch_entity(entity_id: str) -> dict[str, Any]:
    from agentgraph.graph.fetch import fetch_entity_by_id

    try:
        return await fetch_entity_by_id(entity_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/download")
async def query_download(
    entity_id: str,
    output_path: str | None = Query(default=None),
) -> dict[str, Any]:
    """Download to ``output_path``, which the client must send as an absolute path.

    The server writes the file, so a relative path would resolve against the server's
    working directory rather than the caller's.
    """
    from agentgraph.graph.download import download_entity

    try:
        return await download_entity(entity_id, output_path)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/bookmark")
async def query_bookmark(target: str, bookmarked: bool = Query(default=True)) -> dict[str, Any]:
    from agentgraph.graph.bookmark import bookmark_target, set_entity_bookmark

    try:
        if bookmarked:
            return await bookmark_target(target)
        return await set_entity_bookmark(target, False)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/delete")
async def query_delete(target: str) -> dict[str, Any]:
    from agentgraph.graph.delete import delete_entity

    try:
        return await delete_entity(target)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/unify-persons")
async def query_unify_persons(
    canonical_id: str,
    duplicate_ids: list[str] = Query(default_factory=list),
) -> dict[str, Any]:
    from agentgraph.graph.person import unify_persons

    try:
        return await unify_persons(canonical_id, duplicate_ids)
    except ValueError as exc:
        raise _bad_request(exc) from exc
