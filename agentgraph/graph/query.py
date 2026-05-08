"""Shared graph query layer used by both MCP tools and CLI commands."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from agentgraph.core.context import get_backend
from agentgraph.core.storage import EdgeResult, EntityResult
from agentgraph.graph.embeddings import encode


def _enrich_web_url(entities: list[EntityResult]) -> None:
    """Populate metadata.web_url from the connector for entities that don't store it."""
    from agentgraph.connectors.registry import get_connector

    for entity in entities:
        meta = entity.get("metadata")
        if isinstance(meta, dict) and meta.get("web_url"):
            continue
        connector = get_connector(entity.get("platform", ""))
        if connector is None:
            continue
        url = connector.entity_url(entity.get("platform_entity_id", ""))
        if url:
            if not isinstance(meta, dict):
                entity["metadata"] = {"web_url": url}
            else:
                meta["web_url"] = url


async def search_entities(
    query: str,
    entity_types: list[str] | None = None,
    limit: int = 10,
    min_score: float = 0.03,
    platform: str | None = None,
) -> list[EntityResult]:
    """Hybrid search: combines vector similarity with full-text via RRF."""
    embedding = encode(query)
    backend = get_backend()
    results = await backend.search_entities(
        embedding, query, entity_types, limit, min_score, platform=platform
    )
    _enrich_web_url(results)
    if results:
        ids = [r["id"] for r in results]
        asyncio.create_task(backend.touch_last_accessed_by_ids(ids))
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
        pid = parts[-1]
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
    order_by: str = "last_accessed",
    since: str | None = None,
    authored_by_me: bool = False,
    has_attachments: bool = False,
) -> list[EntityResult]:
    since_dt = _parse_since(since) if since else None
    authored_by: str | None = _resolve_me() if authored_by_me else None
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
    since_dt = _parse_since(since) if since else None
    results = await get_backend().list_entities(entity_types, platform, since_dt, limit)
    _enrich_web_url(results)
    return results


async def get_edges_for_entities(entity_ids: list[str]) -> list[EdgeResult]:
    return await get_backend().get_edges_for_entities(entity_ids)


async def get_entities_by_ids(entity_ids: list[str]) -> list[EntityResult]:
    results = await get_backend().get_entities_by_ids(entity_ids)
    _enrich_web_url(results)
    return results


def _resolve_me() -> str | None:
    """Return the current user's email or Slack user ID from stored credentials."""
    from agentgraph.auth.credentials import load_platform
    from agentgraph.auth.google_provider import get_user_email as google_user_email

    email = google_user_email()
    if email:
        return email
    slack = load_platform("slack")
    if slack and slack.get("user_id"):
        return str(slack["user_id"])
    return None


def _parse_since(since: str) -> datetime:
    """Parse a relative duration (12h, 30m, 2d) or ISO timestamp string."""
    m = re.fullmatch(r"(\d+)(h|m|d)", since.strip())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"h": timedelta(hours=n), "m": timedelta(minutes=n), "d": timedelta(days=n)}[unit]
        return datetime.now(UTC) - delta
    return datetime.fromisoformat(since)
