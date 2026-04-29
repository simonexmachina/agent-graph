"""Shared graph query layer used by both MCP tools and CLI commands."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from agentgraph.core.context import get_backend
from agentgraph.core.storage import EdgeResult, EntityResult
from agentgraph.graph.embeddings import encode


async def search_entities(
    query: str,
    entity_types: list[str] | None = None,
    limit: int = 10,
    min_score: float = 0.03,
) -> list[EntityResult]:
    """Hybrid search: combines vector similarity with full-text via RRF."""
    embedding = encode(query)
    return await get_backend().search_entities(embedding, query, entity_types, limit, min_score)


async def get_entity(entity_id: str) -> EntityResult | None:
    """Fetch a single entity by UUID, unambiguous UUID prefix, or platform ref.

    Platform ref formats accepted:
      - ``"{platform}/{platform_entity_id}"``
      - ``"{platform}/{resource_type}/{platform_entity_id}"``  (resource_type ignored)
    """
    backend = get_backend()
    if len(entity_id) == 36 or (len(entity_id) == 32 and "-" not in entity_id):
        return await backend.get_entity_by_id(entity_id)
    if "/" in entity_id:
        parts = entity_id.split("/")
        platform = parts[0]
        pid = parts[-1]
        return await backend.get_entity_by_platform(platform, pid)
    # UUID prefix — must be unambiguous
    results = await backend.get_entities_by_id_prefix(entity_id)
    if len(results) > 1:
        raise ValueError(
            f"Ambiguous prefix {entity_id!r} matches {len(results)} entities"
        )
    return results[0] if results else None


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
) -> list[EntityResult]:
    since_dt = _parse_since(since) if since else None
    authored_by: str | None = _resolve_me() if authored_by_me else None
    return await get_backend().query_by_filter(
        entity_type, filters, limit, order_by, since_dt, authored_by
    )


async def list_entities(
    entity_types: list[str] | None = None,
    platform: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[EntityResult]:
    since_dt = _parse_since(since) if since else None
    return await get_backend().list_entities(entity_types, platform, since_dt, limit)


async def get_edges_for_entities(entity_ids: list[str]) -> list[EdgeResult]:
    return await get_backend().get_edges_for_entities(entity_ids)


def _resolve_me() -> str | None:
    """Return the current user's email or Slack user ID from the configured provider."""
    from agentgraph.auth.credentials import load as load_creds
    from agentgraph.auth.google_provider import get_provider

    email = get_provider().get_user_email()
    if email:
        return email
    stored = load_creds()
    if stored.slack and stored.slack.user_id:
        return stored.slack.user_id
    return None


def _parse_since(since: str) -> datetime:
    """Parse a relative duration (12h, 30m, 2d) or ISO timestamp string."""
    m = re.fullmatch(r"(\d+)(h|m|d)", since.strip())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"h": timedelta(hours=n), "m": timedelta(minutes=n), "d": timedelta(days=n)}[unit]
        return datetime.now(UTC) - delta
    return datetime.fromisoformat(since)
