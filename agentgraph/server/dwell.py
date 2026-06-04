"""Dwell dispatch: classifies a URL and fires a connector fetch."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agentgraph.connectors.base import ResourceType
from agentgraph.server.router import classify_url

logger = logging.getLogger(__name__)


async def record_dwell_time(url: str, dwell_ms: int, meta: dict[str, str] | None = None) -> dict[str, Any]:
    """Classify url and increment its cumulative dwell time in the backend."""
    ref = classify_url(url)
    if ref is None:
        logger.debug("report-dwell: unrecognised URL %s", url)
        return {"status": "ignored", "reason": "unrecognised URL"}

    from agentgraph.config import get_settings
    from agentgraph.core.context import get_backend

    try:
        backend = get_backend()
        await backend.increment_dwell_time(ref.source, ref.resource_id, dwell_ms)
        logger.debug(
            "Recorded dwell time: +%dms for %s %s/%s",
            dwell_ms, ref.source, ref.resource_type, ref.resource_id
        )

        # Dispatch background connector fetch if the dwell time meets the threshold
        threshold_ms = get_settings().dwell_threshold_seconds * 1000
        if dwell_ms >= threshold_ms:
            logger.info(
                "Dwell threshold met (%dms >= %dms): dispatching fetch for %s %s/%s",
                dwell_ms, threshold_ms, ref.source, ref.resource_type, ref.resource_id
            )
            asyncio.create_task(_dispatch(ref.source, ref.resource_type, ref.resource_id, meta))

        return {"status": "accepted", "source": ref.source, "resource_type": ref.resource_type}
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
        logger.info(
            "Fetch complete %s/%s/%s — %d entities, %d persons, %d edges",
            source, resource_type, resource_id,
            len(batch.entities), len(batch.persons), len(batch.edges),
        )
    except Exception:
        logger.exception("Connector fetch failed: %s/%s/%s", source, resource_type, resource_id)
