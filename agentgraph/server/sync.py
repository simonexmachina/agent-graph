"""SyncEngine: background polling for all connectors with poll_interval set."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

from agentgraph.connectors.base import BaseConnector
from agentgraph.graph.upsert import upsert_batch

logger = logging.getLogger(__name__)


async def _load_cursor(source: str) -> dict[str, Any]:
    from agentgraph.db.connection import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT cursor FROM sync_state WHERE source = $1",
            source,
        )
    if not row:
        return {}
    val = row["cursor"]
    return __import__("json").loads(val) if isinstance(val, str) else dict(val)


async def _save_cursor(source: str, cursor: dict[str, Any]) -> None:
    from agentgraph.db.connection import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sync_state (source, cursor, updated_at)
            VALUES ($1, $2::jsonb, now())
            ON CONFLICT (source) DO UPDATE
                SET cursor = EXCLUDED.cursor, updated_at = now()
            """,
            source,
            __import__("json").dumps(cursor),
        )


async def _poll_connector(connector: BaseConnector) -> None:
    source = connector.source
    try:
        cursor = await _load_cursor(source)
        batch, cursor = await connector.poll(cursor)
        if batch.entities or batch.persons or batch.edges:
            await upsert_batch(batch)
        await _save_cursor(source, cursor)
        logger.debug(
            "poll %s — %d entities, %d persons, %d edges",
            source, len(batch.entities), len(batch.persons), len(batch.edges),
        )
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
            connector.source, total_seconds,
        )
