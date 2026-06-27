"""SyncEngine: background polling for all connectors with poll_interval set."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import logging
from time import perf_counter

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

from agentgraph.connectors.base import BaseConnector
from agentgraph.core.context import get_backend
from agentgraph.graph.upsert import upsert_batch

logger = logging.getLogger(__name__)


def _sync_scope(source: str, account_id: str | None) -> str:
    return source if account_id is None else f"{source}:{account_id}"


async def poll_connector(connector: BaseConnector) -> None:
    source = connector.source
    started = perf_counter()
    try:
        backend = get_backend()
        for account_id in connector.poll_account_ids():
            scope_started = perf_counter()
            scope = _sync_scope(source, account_id)
            cursor = await backend.load_cursor(scope)
            is_first_run = not cursor
            logger.info(
                "poll %s — starting%s",
                scope,
                " (first run / bulk ingest)" if is_first_run else "",
            )

            batch, new_cursor = await connector.poll(cursor, account_id=account_id)

            n_entities = len(batch.entities)
            n_persons = len(batch.persons)
            n_edges = len(batch.edges)

            if batch.entities or batch.persons or batch.edges:
                logger.info(
                    "poll %s — upserting %d entities, %d persons, %d edges",
                    scope, n_entities, n_persons, n_edges,
                )
                await upsert_batch(batch)
                logger.info("poll %s — upsert complete", scope)
            else:
                logger.info("poll %s — no new data", scope)

            await backend.save_cursor(scope, new_cursor)
            logger.info("poll %s — completed in %.1fs", scope, perf_counter() - scope_started)
    except Exception:
        logger.exception("poll failed for connector %s", source)
    finally:
        logger.debug("poll %s total elapsed %.1fs", source, perf_counter() - started)


async def run_ingest(connector: BaseConnector) -> None:
    source = connector.source
    started = perf_counter()
    try:
        for account_id in connector.poll_account_ids():
            scope_started = perf_counter()
            scope = _sync_scope(source, account_id)
            logger.info("ingest %s — starting", scope)
            batch = await connector.ingest(account_id=account_id)
            if batch.entities or batch.persons or batch.edges:
                logger.info(
                    "ingest %s — upserting %d entities, %d persons, %d edges",
                    scope, len(batch.entities), len(batch.persons), len(batch.edges),
                )
                await upsert_batch(batch)
                logger.info("ingest %s — complete in %.1fs", scope, perf_counter() - scope_started)
            else:
                logger.info("ingest %s — no data returned", scope)
    except Exception:
        logger.exception("ingest failed for connector %s", source)
    finally:
        logger.debug("ingest %s total elapsed %.1fs", source, perf_counter() - started)


def setup_sync(scheduler: AsyncIOScheduler) -> None:
    """Register a poll job for every connector that has poll_interval set."""
    from agentgraph.connectors.registry import get_all_connectors

    for connector in get_all_connectors():
        interval = connector.poll_interval
        if interval is None:
            continue
        total_seconds = int(interval.total_seconds())
        scheduler.add_job(
            poll_connector,
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
