"""Shared graph query layer used by both MCP tools and CLI commands."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, cast
from urllib.parse import urlparse

from agentgraph.core.context import get_backend
from agentgraph.core.storage import EdgeResult, EntityResult


@lru_cache(maxsize=256)
def _cached_query_embedding(query: str) -> tuple[float, ...]:
    from agentgraph.graph.embeddings import encode_query

    return tuple(encode_query(query))


def clear_query_embedding_cache() -> None:
    _cached_query_embedding.cache_clear()


def _enrich_web_url(entities: list[EntityResult]) -> None:
    """Populate metadata.web_url from the connector for entities that don't store it."""
    from agentgraph.connectors.registry import get_connector

    connectors: dict[str, Any] = {}
    for entity in entities:
        meta = entity.get("metadata")
        metadata = cast(dict[str, Any], meta) if isinstance(meta, dict) else None
        if metadata is not None and metadata.get("web_url"):
            continue
        platform = entity.get("platform")
        if not isinstance(platform, str):
            continue
        if platform not in connectors:
            connectors[platform] = get_connector(platform)
        connector = connectors[platform]
        if connector is None:
            continue
        platform_entity_id = entity.get("platform_entity_id")
        url = connector.entity_url(platform_entity_id if isinstance(platform_entity_id, str) else "")
        if url:
            if metadata is None:
                entity["metadata"] = {"web_url": url}
            else:
                metadata["web_url"] = url


async def search_entities(
    query: str,
    entity_types: list[str] | None = None,
    limit: int = 10,
    min_score: float = 0.03,
    platform: str | None = None,
) -> list[EntityResult]:
    """Hybrid search: combines vector similarity with full-text via RRF."""
    embedding = list(await asyncio.to_thread(_cached_query_embedding, query))
    backend = get_backend()
    results = await backend.search_entities(
        embedding, query, entity_types, limit, min_score, platform=platform
    )
    _enrich_web_url(results)
    return results


async def get_entity(entity_id: str) -> EntityResult | None:
    """Fetch a single entity by UUID, unambiguous UUID prefix, or platform ref.

    Platform ref formats accepted:
      - ``"{platform}/{platform_entity_id}"``
      - ``"{platform}/{resource_type}/{platform_entity_id}"``  (resource_type ignored)
    """
    backend = get_backend()
    entity: EntityResult | None
    if len(entity_id) == 36 or (len(entity_id) == 32 and "-" not in entity_id):
        entity = await backend.get_entity_by_id(entity_id)
    elif "/" in entity_id:
        parts = entity_id.split("/")
        platform = parts[0]
        pid = "/".join(parts[2:]) if len(parts) >= 3 else "/".join(parts[1:])
        entity = await backend.get_entity_by_platform(platform, pid)
    else:
        # UUID prefix — must be unambiguous
        results = await backend.get_entities_by_id_prefix(entity_id)
        if len(results) > 1:
            raise ValueError(
                f"Ambiguous prefix {entity_id!r} matches {len(results)} entities"
            )
        entity = results[0] if results else None
    if entity is not None:
        _enrich_web_url([entity])
    return entity


async def get_entity_by_url(url: str) -> EntityResult | None:
    """Fetch a single existing entity by URL without fetching or creating it."""
    from agentgraph.connectors.registry import bootstrap, get_connector
    from agentgraph.server.router import classify_url, normalise_url_for_matching

    normalised_url = normalise_url_for_matching(url)
    bootstrap()
    ref = classify_url(normalised_url)
    backend = get_backend()

    if ref is not None:
        entity = await backend.get_entity_by_platform(ref.source, ref.resource_id)
        if entity is not None:
            _enrich_web_url([entity])
        return entity

    connector = get_connector("web")
    web_ref = connector.resolve_url(normalised_url) if connector is not None else None
    if web_ref is None:
        return None

    entity = await backend.get_entity_by_platform(web_ref.source, web_ref.resource_id)
    if entity is None:
        entity = await _get_web_entity_by_metadata_url(normalised_url)
    if entity is not None:
        _enrich_web_url([entity])
    return entity


async def get_edges(
    entity_id: str,
    edge_type: str | None = None,
    direction: str = "both",
) -> list[EdgeResult]:
    return await get_backend().get_edges(entity_id, edge_type, direction)


async def traverse_graph(
    entity_id: str,
    max_depth: int = 2,
) -> dict[str, Any]:
    return await get_backend().traverse_graph(entity_id, max_depth)


async def query_by_filter(
    entity_type: str,
    filters: dict[str, str],
    limit: int = 50,
    order_by: str = "observed_at",
    since: str | None = None,
    authored_by_me: bool = False,
    has_attachments: bool = False,
) -> list[EntityResult]:
    since_dt = parse_since(since) if since else None
    authored_by: list[str] | None = _resolve_me() if authored_by_me else None
    results = await get_backend().query_by_filter(
        entity_type, filters, limit, order_by, since_dt, authored_by,
        has_attachments=has_attachments,
    )
    _enrich_web_url(results)
    return results


async def list_entities(
    entity_types: list[str] | None = None,
    platform: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[EntityResult]:
    since_dt = parse_since(since) if since else None
    results = await get_backend().list_entities(entity_types, platform, since_dt, limit)
    _enrich_web_url(results)
    return results


async def list_entities_page(
    entity_types: list[str] | None = None,
    platform: str | None = None,
    since: str | None = None,
    limit: int = 50,
    offset: int = 0,
    order_by: str | None = "observed_at",
    order_dir: str = "desc",
) -> tuple[list[EntityResult], int]:
    since_dt = parse_since(since) if since else None
    results, total = await get_backend().list_entities_page(
        entity_types, platform, since_dt, limit, offset, order_by, order_dir
    )
    _enrich_web_url(results)
    return results, total


async def get_edges_for_entities(entity_ids: list[str]) -> list[EdgeResult]:
    return await get_backend().get_edges_for_entities(entity_ids)


async def get_entities_by_ids(entity_ids: list[str]) -> list[EntityResult]:
    results = await get_backend().get_entities_by_ids(entity_ids)
    _enrich_web_url(results)
    return results


def _resolve_me() -> list[str] | None:
    """Return the current user's canonical identifiers by polling registered connectors."""
    from agentgraph.connectors.registry import get_all_connectors
    user_ids: list[str] = []
    for connector in get_all_connectors():
        for user_id in type(connector).current_user_ids():
            if user_id not in user_ids:
                user_ids.append(user_id)
    return user_ids or None


async def _get_web_entity_by_metadata_url(url: str) -> EntityResult | None:
    backend = get_backend()
    for key in ("url", "final_url"):
        results = await backend.query_by_filter(
            "Document",
            {"platform": "web", key: url},
            1,
            "updated_at",
            None,
            None,
        )
        if results:
            return results[0]
    return None


def is_http_url(target: str) -> bool:
    parsed = urlparse(target)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def parse_since(since: str) -> datetime:
    """Parse a relative duration (12h, 30m, 2d) or ISO timestamp string."""
    m = re.fullmatch(r"(\d+)(h|m|d)", since.strip())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"h": timedelta(hours=n), "m": timedelta(minutes=n), "d": timedelta(days=n)}[unit]
        return datetime.now(UTC) - delta
    return datetime.fromisoformat(since)
