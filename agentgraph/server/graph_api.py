"""Graph API router — admin endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["graph"])


@router.post("/admin/relink")
async def relink_all() -> dict[str, Any]:
    """Re-run URL reference linking for all entities that have content.

    Creates stub entities for any classifiable URLs not yet in the graph.
    Safe to call multiple times — uses ON CONFLICT DO NOTHING/UPDATE.
    """
    from agentgraph.core.context import get_backend
    from agentgraph.graph.link import link_entity_to_urls

    rows = await get_backend().list_entities(
        entity_types=None,
        platform=None,
        since=None,
        limit=100_000,
    )

    total_links = 0
    for row in rows:
        content = row.get("content")
        platform = row.get("platform")
        platform_entity_id = row.get("platform_entity_id")
        if not (
            isinstance(content, str)
            and isinstance(platform, str)
            and isinstance(platform_entity_id, str)
        ):
            continue
        total_links += await link_entity_to_urls(
            platform_entity_id,
            platform,
            content,
        )

    return {"relinked": len(rows), "edges_created": total_links}
