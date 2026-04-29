"""Dwell evaluator: detects sustained focus events and dispatches fetches."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from agentgraph.config import get_settings
from agentgraph.connectors.base import ResourceType
from agentgraph.core.context import get_backend
from agentgraph.server.router import classify_url

logger = logging.getLogger(__name__)


async def evaluate_once() -> None:
    """
    Scan for focus events older than dwell_threshold that have no matching
    blur event. Dispatch a fetch for each, then mark them evaluated.
    """
    settings = get_settings()
    threshold = timedelta(seconds=settings.dwell_threshold_seconds)
    cutoff = datetime.now(UTC) - threshold

    backend = get_backend()
    rows = await backend.get_pending_observations(cutoff)

    for row in rows:
        ref = classify_url(row["url"])
        if ref is not None:
            import json as _json

            meta: dict[str, str] | None = None
            if row["meta"]:
                try:
                    meta = _json.loads(row["meta"])
                except Exception:
                    pass
            logger.info(
                "Dwell detected: %s %s/%s (tab %s)",
                ref.source,
                ref.resource_type,
                ref.resource_id,
                row["tab_id"],
            )
            asyncio.create_task(
                _dispatch(ref.source, ref.resource_type, ref.resource_id, meta)
            )

        await backend.mark_observation_evaluated(row["id"])


async def _dispatch(
    source: str,
    resource_type: ResourceType,
    resource_id: str,
    meta: dict[str, str] | None = None,
) -> None:
    """Fire-and-forget connector fetch."""
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
            source,
            resource_type,
            resource_id,
            len(batch.entities),
            len(batch.persons),
            len(batch.edges),
        )
    except Exception:
        logger.exception(
            "Connector fetch failed: %s/%s/%s", source, resource_type, resource_id
        )


async def run_dwell_loop() -> None:
    """Background task: run evaluate_once on a fixed interval."""
    settings = get_settings()
    interval = settings.dwell_poll_interval_seconds
    logger.info("Dwell evaluator started (poll interval: %ss)", interval)
    while True:
        try:
            await evaluate_once()
        except Exception:
            logger.exception("Dwell evaluator error")
        await asyncio.sleep(interval)
