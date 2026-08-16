"""Transport-independent graph operations shared by CLI, MCP, and HTTP."""

from __future__ import annotations

from typing import Any

from agentgraph.core.storage import EdgeResult, EntityResult
from agentgraph.graph.query import (
    get_edges,
    get_entity,
    get_entity_by_url,
    is_http_url,
    traverse_graph,
)


def is_stub(entity: EntityResult) -> bool:
    """Return whether an entity has no fetched title or content."""
    return not entity.get("title") and not entity.get("content")


def summarize_entity(entity: EntityResult, *, content_limit: int = 500) -> EntityResult:
    """Copy an entity and bound its content for list-style responses."""
    summarized = dict(entity)
    content = summarized.get("content")
    if isinstance(content, str) and len(content) > content_limit:
        summarized["content"] = content[: max(content_limit - 1, 0)].rstrip() + "…"
        summarized["content_truncated"] = True
    else:
        summarized["content_truncated"] = False
    return summarized


def summarize_entities(
    entities: list[EntityResult],
    *,
    content_limit: int = 500,
) -> list[EntityResult]:
    """Return bounded copies of entities for search and query responses."""
    return [summarize_entity(entity, content_limit=content_limit) for entity in entities]


async def resolve_entity(target: str) -> EntityResult | None:
    """Resolve an existing entity from a UUID, prefix, platform ref, or URL."""
    return await get_entity_by_url(target) if is_http_url(target) else await get_entity(target)


async def get_entity_details(target: str, *, resolve: bool = False) -> EntityResult | None:
    """Resolve an entity and optionally fetch it when it is still a stub."""
    entity = await resolve_entity(target)
    if entity is None or not resolve or not is_stub(entity):
        return entity
    return await refresh_stub(entity)


async def refresh_stub(entity: EntityResult) -> EntityResult:
    """Fetch one stub through its connector and return the refreshed entity."""
    from agentgraph.graph.fetch import fetch_entity_by_id

    entity_id = str(entity["id"])
    await fetch_entity_by_id(entity_id)
    return await get_entity(entity_id) or entity


async def get_entity_edges(
    target: str,
    *,
    edge_type: str | None = None,
    direction: str = "both",
) -> tuple[EntityResult | None, list[EdgeResult]]:
    """Resolve a target and return edges for its canonical entity ID."""
    entity = await resolve_entity(target)
    if entity is None:
        return None, []
    edges = await get_edges(str(entity["id"]), edge_type=edge_type, direction=direction)
    return entity, edges


async def traverse_entity(
    target: str,
    *,
    max_depth: int = 2,
    resolve: bool = False,
) -> tuple[EntityResult | None, dict[str, Any]]:
    """Resolve a target, traverse it, and optionally refresh all encountered stubs."""
    entity = await resolve_entity(target)
    if entity is None:
        return None, {}

    canonical_id = str(entity["id"])
    result = await traverse_graph(canonical_id, max_depth=max_depth)
    if resolve:
        stubs = [node for node in result.get("nodes", []) if is_stub(node)]
        for stub in stubs:
            await refresh_stub(stub)
        if stubs:
            result = await traverse_graph(canonical_id, max_depth=max_depth)
    return entity, result
