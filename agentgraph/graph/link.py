"""Cross-platform URL reference linking.

Creates 'references' edges between any entity whose content links to another
known entity (Google Doc, Sheet, Discord channel, Slack channel, etc.).

Two directions, both called from upsert_batch:
  - forward:  entity just ingested → find known URLs in its content
  - backward: entity just ingested → find other entities that link to it
"""

from __future__ import annotations

import logging
import re

from agentgraph.connectors.base import RESOURCE_TYPE_TO_ENTITY_TYPE
from agentgraph.core.context import get_backend

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+")


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

    backend = get_backend()
    src_id = await backend.find_entity_id(platform, platform_entity_id)
    if not src_id:
        return 0

    count = 0
    seen: set[str] = set()
    for ref in refs:
        if ref.resource_id in seen:
            continue
        seen.add(ref.resource_id)

        tgt_id = await backend.find_entity_id(ref.source, ref.resource_id)
        if not tgt_id:
            entity_type = RESOURCE_TYPE_TO_ENTITY_TYPE[ref.resource_type]  # type: ignore[index]
            tgt_id = await backend.upsert_stub_entity(entity_type, ref.source, ref.resource_id)
            logger.debug("Created stub entity %s/%s", ref.source, ref.resource_id)

        await backend.insert_references_edge(src_id, tgt_id)
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
    # Short IDs (display names, single words) produce too many substring false positives.
    # All legitimate URL-embeddable IDs (Gmail thread IDs, Slack channel/message IDs,
    # Google Doc IDs) are at least 8 characters long.
    if len(platform_entity_id) < 8:
        return 0

    backend = get_backend()
    tgt_id = await backend.find_entity_id(platform, platform_entity_id)
    if not tgt_id:
        return 0

    src_ids = await backend.find_entities_containing(
        platform_entity_id, platform, platform_entity_id
    )
    for src_id in src_ids:
        await backend.insert_references_edge(src_id, tgt_id)

    if src_ids:
        logger.info(
            "Created %d references edge(s) → %s/%s",
            len(src_ids), platform, platform_entity_id,
        )
    return len(src_ids)
