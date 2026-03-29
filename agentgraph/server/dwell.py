"""Dwell evaluator: detects sustained focus events and dispatches fetches."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from agentgraph.config import get_settings
from agentgraph.connectors.base import ResourceType
from agentgraph.db.connection import get_pool
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

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Find mature, unevaluated focus events
        rows = await conn.fetch(
            """
            SELECT o.id, o.url, o.tab_id, o.timestamp, o.meta
            FROM observations o
            WHERE o.event_type = 'focus'
              AND o.evaluated = false
              AND o.timestamp < $1
              AND NOT EXISTS (
                  SELECT 1 FROM observations b
                  WHERE b.event_type = 'blur'
                    AND b.tab_id = o.tab_id
                    AND b.timestamp > o.timestamp
                    AND b.timestamp < $1
              )
            ORDER BY o.timestamp
            """,
            cutoff,
        )

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
                # Dispatch to connector (imported here to avoid circular deps)
                asyncio.create_task(_dispatch(ref.source, ref.resource_type, ref.resource_id, meta))

            # Mark evaluated regardless of whether we recognised the URL
            await conn.execute(
                "UPDATE observations SET evaluated = true WHERE id = $1",
                row["id"],
            )


async def _dispatch(source: str, resource_type: ResourceType, resource_id: str, meta: dict[str, str] | None = None) -> None:
    """Fire-and-forget connector fetch."""
    from agentgraph.connectors.registry import get_connector

    connector = get_connector(source)
    if connector is None:
        logger.debug("No connector registered for source '%s'", source)
        return
    try:
        logger.info("Fetching %s/%s/%s", source, resource_type, resource_id)
        batch = await connector.fetch(resource_type=resource_type, resource_id=resource_id, meta=meta)
        logger.info(
            "Fetch complete %s/%s/%s — %d entities, %d persons, %d edges",
            source, resource_type, resource_id,
            len(batch.entities), len(batch.persons), len(batch.edges),
        )
    except Exception:
        logger.exception("Connector fetch failed: %s/%s/%s", source, resource_type, resource_id)


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
