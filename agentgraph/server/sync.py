"""SyncEngine: background polling for all connectors with poll_interval set."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from time import perf_counter

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

from agentgraph.connectors.base import BaseConnector
from agentgraph.connectors.status import connector_uses_auth
from agentgraph.core.context import get_backend
from agentgraph.graph.upsert import upsert_batch

logger = logging.getLogger(__name__)

_failure_counts: dict[str, int] = {}
_backoff_until: dict[str, datetime] = {}


def clear_poll_backoff() -> None:
    _failure_counts.clear()
    _backoff_until.clear()


def _sync_scope(source: str, account_id: str | None) -> str:
    return source if account_id is None else f"{source}:{account_id}"


def _has_local_auth(connector: BaseConnector) -> bool:
    if not connector_uses_auth(connector):
        return True
    accounts = type(connector).list_accounts()
    if accounts:
        return True
    return type(connector).get_authenticated_user() is not None


def _backoff_remaining(source: str) -> timedelta | None:
    until = _backoff_until.get(source)
    if until is None:
        return None
    remaining = until - datetime.now(UTC)
    if remaining <= timedelta(0):
        _backoff_until.pop(source, None)
        return None
    return remaining


def _record_success(source: str) -> None:
    _failure_counts.pop(source, None)
    _backoff_until.pop(source, None)


def _record_failure(source: str) -> None:
    count = _failure_counts.get(source, 0) + 1
    _failure_counts[source] = count
    delay = min(60 * (2 ** (count - 1)), 3600)
    _backoff_until[source] = datetime.now(UTC) + timedelta(seconds=delay)
    logger.warning("poll %s — backing off for %ds after %d failure(s)", source, delay, count)


async def poll_connector(connector: BaseConnector) -> None:
    source = connector.source
    started = perf_counter()
    remaining = _backoff_remaining(source)
    if remaining is not None:
        logger.info("poll %s — skipped during failure backoff (%.0fs remaining)", source, remaining.total_seconds())
        return
    if not _has_local_auth(connector):
        logger.info("poll %s — skipped because authentication is not configured", source)
        return
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
        _record_success(source)
    except Exception:
        _record_failure(source)
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
            name=f"poll connector {connector.source}",
            max_instances=1,
            coalesce=True,
        )
        logger.info(
            "Scheduled background poll for %s every %ds",
            connector.source,
            total_seconds,
        )
