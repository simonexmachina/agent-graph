"""SyncEngine: background polling for all connectors with poll_interval set."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

from agentgraph.connectors.base import BaseConnector
from agentgraph.core.context import get_backend
from agentgraph.graph.upsert import upsert_batch

logger = logging.getLogger(__name__)


async def _poll_connector(connector: BaseConnector) -> None:
    source = connector.source
    try:
        backend = get_backend()
        cursor = await backend.load_cursor(source)
        is_first_run = not cursor
        logger.info("poll %s — starting%s", source, " (first run / bulk ingest)" if is_first_run else "")

        batch, new_cursor = await connector.poll(cursor)

        n_entities = len(batch.entities)
        n_persons = len(batch.persons)
        n_edges = len(batch.edges)

        if batch.entities or batch.persons or batch.edges:
            logger.info(
                "poll %s — upserting %d entities, %d persons, %d edges",
                source, n_entities, n_persons, n_edges,
            )
            await upsert_batch(batch)
            logger.info("poll %s — upsert complete", source)
        else:
            logger.info("poll %s — no new data", source)

        await backend.save_cursor(source, new_cursor)
        logger.info("poll %s — completed", source)
    except Exception:
        logger.exception("poll failed for connector %s", source)


def setup_sync(scheduler: AsyncIOScheduler) -> None:
    """Register a poll job for every connector that has poll_interval set."""
    from agentgraph.connectors.registry import get_all_connectors

    for connector in get_all_connectors():
        interval = connector.poll_interval
        if interval is None:
            continue
        total_seconds = int(interval.total_seconds())
        scheduler.add_job(
            _poll_connector,
            "interval",
            seconds=total_seconds,
            args=[connector],
            id=f"sync_{connector.source}",
            max_instances=1,
            coalesce=True,
        )
        logger.info(
            "Scheduled background poll for %s every %ds",
            connector.source,
            total_seconds,
        )
