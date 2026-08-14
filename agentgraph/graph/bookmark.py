"""Bookmark graph entities to protect them from expiration."""

from __future__ import annotations

from urllib.parse import urlparse

from agentgraph.core.context import get_backend
from agentgraph.core.storage import EntityResult
from agentgraph.graph.query import get_entity


async def bookmark_entity(entity_id: str) -> EntityResult:
    """Mark an entity as bookmarked by UUID, UUID prefix, or platform ref."""
    return await set_entity_bookmark(entity_id, True)


async def set_entity_bookmark(entity_id: str, bookmarked: bool) -> EntityResult:
    """Set bookmark state by UUID, UUID prefix, or platform ref."""
    entity = await get_entity(entity_id)
    if entity is None:
        raise ValueError(f"Entity {entity_id!r} not found")
    return await get_backend().set_entity_bookmarked(entity["id"], bookmarked)


async def bookmark_target(target: str) -> EntityResult:
    """Bookmark an entity target or fetch and bookmark an http(s) URL."""
    if _is_http_url(target):
        return await bookmark_url(target)
    return await bookmark_entity(target)


async def bookmark_url(url: str) -> EntityResult:
    """Fetch a URL through its owning connector or the web fallback, then bookmark it."""
    from agentgraph.connectors.registry import bootstrap, get_connector
    from agentgraph.graph.upsert import upsert_batch
    from agentgraph.server.router import classify_url

    bootstrap()
    ref = classify_url(url)
    connector = get_connector(ref.source) if ref is not None else get_connector("web")
    if connector is None:
        raise ValueError("No connector available to fetch this URL")

    resource_type = ref.resource_type if ref is not None else "document"
    resource_id = ref.resource_id if ref is not None else url
    batch = await connector.fetch(resource_type, resource_id)

    backend = get_backend()
    if ref is not None:
        entity = await backend.get_entity_by_platform(ref.source, ref.resource_id)
    else:
        entity = None

    if entity is None:
        entity = await _find_batch_entity(batch)

    if entity is None and batch.entities:
        await upsert_batch(batch)
        if ref is not None:
            entity = await backend.get_entity_by_platform(ref.source, ref.resource_id)
        else:
            entity = await _find_batch_entity(batch)

    if entity is None:
        raise ValueError(f"URL {url!r} was fetched but no graph entity was created")
    return await backend.set_entity_bookmarked(entity["id"], True)


async def _find_batch_entity(batch: object) -> EntityResult | None:
    from agentgraph.connectors.base import EntityBatch

    if not isinstance(batch, EntityBatch):
        return None
    backend = get_backend()
    for candidate in batch.entities:
        entity = await backend.get_entity_by_platform(
            candidate.platform,
            candidate.platform_entity_id,
        )
        if entity is not None:
            return entity
    return None


def _is_http_url(target: str) -> bool:
    parsed = urlparse(target)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
