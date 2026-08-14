"""Dwell dispatch: classifies a URL and fires a connector fetch."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agentgraph.connectors.base import RESOURCE_TYPE_TO_ENTITY_TYPE, ResourceType
from agentgraph.server.router import classify_observation_url

logger = logging.getLogger(__name__)


async def record_dwell_time(
    url: str,
    dwell_ms: int,
    observation_id: str,
    observed: bool,
    meta: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Record either a new observation or a dwell-only update."""
    ref = await classify_observation_url(url, meta=meta)
    if ref is None:
        logger.debug("report-dwell: unrecognised URL %s", url)
        return {"status": "ignored", "reason": "unrecognised URL"}

    from agentgraph.core.context import get_backend

    try:
        backend = get_backend()
        await backend.upsert_stub_entity(
            RESOURCE_TYPE_TO_ENTITY_TYPE[ref.resource_type],
            ref.source,
            ref.resource_id,
        )
        observation_created = False
        if observed:
            observation_created = await backend.record_observation_once(
                ref.source,
                ref.resource_id,
                observation_id,
                url,
                dwell_ms,
            )
        else:
            await backend.increment_dwell_time(ref.source, ref.resource_id, dwell_ms)
        logger.debug(
            "Recorded %s: +%dms for %s %s/%s (observation_id=%s)",
            "observation" if observed else "dwell update",
            dwell_ms,
            ref.source,
            ref.resource_type,
            ref.resource_id,
            observation_id,
        )

        if observation_created:
            logger.info(
                "New observation %s: dispatching fetch for %s %s/%s",
                observation_id,
                ref.source,
                ref.resource_type,
                ref.resource_id,
            )
            fetch_meta = dict(meta or {})
            fetch_meta.update(ref.fetch_meta or {})
            asyncio.create_task(
                _dispatch(ref.source, ref.resource_type, ref.resource_id, fetch_meta or None)
            )

        return {
            "status": "accepted",
            "source": ref.source,
            "resource_type": ref.resource_type,
            "observation_created": observation_created,
        }
    except Exception:
        logger.exception("Failed to record dwell time for %s", url)
        return {"status": "error", "reason": "internal backend error"}


async def _dispatch(
    source: str,
    resource_type: ResourceType,
    resource_id: str,
    meta: dict[str, str] | None = None,
) -> None:
    from agentgraph.connectors.registry import get_connector

    connector = get_connector(source)
    if connector is None:
        logger.debug("No connector registered for source '%s'", source)
        return
    try:
        logger.info("Fetching %s/%s/%s", source, resource_type, resource_id)
        batch = await connector.fetch(
            resource_type=resource_type, resource_id=resource_id, meta=meta
        )
        if batch.entities or batch.persons or batch.edges:
            from agentgraph.graph.upsert import upsert_batch

            await upsert_batch(batch)
        logger.info(
            "Fetch complete %s/%s/%s — %d entities, %d persons, %d edges",
            source, resource_type, resource_id,
            len(batch.entities), len(batch.persons), len(batch.edges),
        )
    except Exception:
        logger.exception("Connector fetch failed: %s/%s/%s", source, resource_type, resource_id)
