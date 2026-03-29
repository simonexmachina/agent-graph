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
    from agentgraph.db.connection import get_pool
    from agentgraph.graph.link import link_entity_to_urls

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT platform, platform_entity_id, content FROM entities WHERE content IS NOT NULL"
        )

    total_links = 0
    for row in rows:
        total_links += await link_entity_to_urls(
            row["platform_entity_id"], row["platform"], row["content"]
        )

    return {"relinked": len(rows), "edges_created": total_links}
