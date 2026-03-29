"""Cross-platform URL reference linking.

Creates 'references' edges between any entity whose content links to another
known entity (Google Doc, Sheet, Discord channel, Slack channel, etc.).

Two directions, both called from upsert_batch:
  - forward:  entity just ingested → find known URLs in its content
  - backward: entity just ingested → find other entities that link to it
"""

from __future__ import annotations

import json
import logging
import re

from agentgraph.connectors.base import RESOURCE_TYPE_TO_ENTITY_TYPE

logger = logging.getLogger(__name__)

# Broad URL extractor — classify_url does the fine-grained matching
_URL_RE = re.compile(r"https?://\S+")

_INSERT_EDGE = """
    INSERT INTO edges
        (edge_type, source_entity_id, target_entity_id, platform, properties)
    VALUES ('references', $1, $2, 'cross', $3)
    ON CONFLICT (edge_type, source_entity_id, target_entity_id) DO NOTHING
"""


async def link_entity_to_urls(platform_entity_id: str, platform: str, content: str) -> int:
    """Create 'references' edges from an entity to any known entities it links to.

    Extracts all URLs from content, classifies each via the router, and creates
    an edge to any matching entity already in the graph.
    Returns the number of edges created.
    """
    from agentgraph.server.router import classify_url

    refs = []
    for url in _URL_RE.findall(content):
        ref = classify_url(url.rstrip(".,)>\"'"))
        if ref:
            refs.append(ref)

    if not refs:
        return 0

    from agentgraph.db.connection import get_pool

    pool = await get_pool()
    count = 0
    async with pool.acquire() as conn:  # type: ignore[attr-defined]
        src_row = await conn.fetchrow(  # type: ignore[attr-defined]
            "SELECT id FROM entities WHERE platform = $1 AND platform_entity_id = $2",
            platform,
            platform_entity_id,
        )
        if not src_row:
            return 0

        seen: set[str] = set()
        for ref in refs:
            if ref.resource_id in seen:
                continue
            seen.add(ref.resource_id)

            tgt_row = await conn.fetchrow(  # type: ignore[attr-defined]
                "SELECT id FROM entities WHERE platform = $1 AND platform_entity_id = $2",
                ref.source,
                ref.resource_id,
            )
            if not tgt_row:
                # Create a stub so the reference is visible before the content is fetched.
                # synced_at is NULL so the connector always treats it as stale.
                entity_type = RESOURCE_TYPE_TO_ENTITY_TYPE[ref.resource_type]  # type: ignore[index]
                tgt_id = await conn.fetchval(  # type: ignore[attr-defined]
                    """
                    INSERT INTO entities (entity_type, platform, platform_entity_id, synced_at)
                    VALUES ($1, $2, $3, NULL)
                    ON CONFLICT (platform, platform_entity_id) DO UPDATE
                        SET last_accessed = now()
                    RETURNING id
                    """,
                    entity_type,
                    ref.source,
                    ref.resource_id,
                )
                tgt_row = {"id": tgt_id}
                logger.debug("Created stub entity %s/%s", ref.source, ref.resource_id)

            await conn.execute(_INSERT_EDGE, src_row["id"], tgt_row["id"], json.dumps({}))  # type: ignore[attr-defined]
            logger.debug(
                "Linked %s/%s → %s/%s",
                platform, platform_entity_id, ref.source, ref.resource_id,
            )
            count += 1

    return count


async def link_entity_from_content(platform_entity_id: str, platform: str) -> int:
    """Create 'references' edges from any entities whose content links to this one.

    Called after any entity is ingested. Searches all entity content for the
    platform_entity_id (which appears in any URL pointing at this entity).
    Returns the number of edges created.
    """
    from agentgraph.db.connection import get_pool

    pool = await get_pool()
    count = 0
    async with pool.acquire() as conn:  # type: ignore[attr-defined]
        tgt_row = await conn.fetchrow(  # type: ignore[attr-defined]
            "SELECT id FROM entities WHERE platform = $1 AND platform_entity_id = $2",
            platform,
            platform_entity_id,
        )
        if not tgt_row:
            return 0

        src_rows = await conn.fetch(  # type: ignore[attr-defined]
            """
            SELECT id FROM entities
            WHERE content LIKE '%' || $1 || '%'
              AND NOT (platform = $2 AND platform_entity_id = $3)
            """,
            platform_entity_id,
            platform,
            platform_entity_id,
        )
        for src_row in src_rows:
            await conn.execute(_INSERT_EDGE, src_row["id"], tgt_row["id"], json.dumps({}))  # type: ignore[attr-defined]
            count += 1

    if count:
        logger.info(
            "Created %d references edge(s) → %s/%s", count, platform, platform_entity_id
        )
    return count
