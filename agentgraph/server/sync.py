"""SyncEngine: background polling for all connectors with poll_interval set."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Literal, TypedDict, cast

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

from agentgraph.connectors.base import BaseConnector
from agentgraph.connectors.status import connector_uses_auth
from agentgraph.core.context import get_backend
from agentgraph.graph.upsert import upsert_batch

logger = logging.getLogger(__name__)

_failure_counts: dict[str, int] = {}
_backoff_until: dict[str, datetime] = {}
_manual_poll_tasks: dict[str, asyncio.Task[None]] = {}
_active_poll_tasks: dict[str, set[asyncio.Task[None]]] = {}


PollScheduleStatus = Literal["queued", "already_running", "skipped"]


class PollScheduleResult(TypedDict):
    source: str
    status: PollScheduleStatus
    reason: str | None


def clear_poll_backoff() -> None:
    _failure_counts.clear()
    _backoff_until.clear()
    _manual_poll_tasks.clear()
    _active_poll_tasks.clear()


async def shutdown_poll_tasks(*, timeout: float = 10.0) -> None:
    """Cancel in-flight poll tasks and wait briefly for their cleanup handlers."""
    active_tasks = [task for tasks in _active_poll_tasks.values() for task in tasks]
    tasks = {task for task in [*_manual_poll_tasks.values(), *active_tasks] if not task.done()}
    if not tasks:
        _manual_poll_tasks.clear()
        _active_poll_tasks.clear()
        return

    for task in tasks:
        task.cancel()
    try:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
    except TimeoutError:
        logger.warning("timed out waiting for %d poll task(s) to stop", len(tasks))
    finally:
        _manual_poll_tasks.clear()
        _active_poll_tasks.clear()


async def schedule_poll_connector(connector: BaseConnector) -> PollScheduleResult:
    """Start a manual background poll unless one is already running."""
    source = connector.source
    existing = _manual_poll_tasks.get(source)
    if existing is not None and not existing.done():
        logger.info("poll %s — manual trigger skipped because a poll is already running", source)
        return {"source": source, "status": "already_running", "reason": None}

    auth_skip_reason = await _auth_skip_reason(connector)
    if auth_skip_reason is not None:
        logger.info("poll %s — manual trigger skipped: %s", source, auth_skip_reason)
        return {"source": source, "status": "skipped", "reason": auth_skip_reason}

    task = asyncio.create_task(poll_connector(connector))
    _manual_poll_tasks[source] = task
    task.add_done_callback(lambda done_task: _manual_poll_tasks.pop(source, None))
    return {"source": source, "status": "queued", "reason": None}


async def _auth_skip_reason(connector: BaseConnector) -> str | None:
    if not connector_uses_auth(connector):
        return None

    try:
        account_ids = connector.poll_account_ids()
        statuses = [await type(connector).verify_auth(account_id) for account_id in account_ids]
    except Exception as exc:
        return f"authentication check failed: {type(exc).__name__}"

    invalid = next(((status, detail) for status, detail in statuses if status == "invalid"), None)
    if invalid is not None:
        detail = invalid[1]
        return f"authentication invalid: {detail}" if detail else "authentication invalid"

    if not any(status == "ok" for status, _ in statuses):
        return "authentication missing"

    return None


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
    task = cast(asyncio.Task[None] | None, asyncio.current_task())
    if task is not None:
        _active_poll_tasks.setdefault(source, set()).add(task)
    started = perf_counter()
    try:
        remaining = _backoff_remaining(source)
        if remaining is not None:
            logger.info(
                "poll %s — skipped during failure backoff (%.0fs remaining)",
                source,
                remaining.total_seconds(),
            )
            return
        if not _has_local_auth(connector):
            logger.info("poll %s — skipped because authentication is not configured", source)
            return
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
            n_metadata_patches = len(batch.metadata_patches)
            n_persons = len(batch.persons)
            n_edges = len(batch.edges)

            if batch.has_writes():
                logger.info(
                    "poll %s — applying %d entities, %d metadata patches, %d persons, %d edges",
                    scope,
                    n_entities,
                    n_metadata_patches,
                    n_persons,
                    n_edges,
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
        if task is not None:
            tasks = _active_poll_tasks.get(source)
            if tasks is not None:
                tasks.discard(task)
                if not tasks:
                    _active_poll_tasks.pop(source, None)
        logger.debug("poll %s total elapsed %.1fs", source, perf_counter() - started)


async def run_ingest(
    connector: BaseConnector,
    account_ids: list[str] | None = None,
) -> None:
    source = connector.source
    started = perf_counter()
    try:
        for account_id in account_ids if account_ids is not None else connector.poll_account_ids():
            scope_started = perf_counter()
            scope = _sync_scope(source, account_id)
            logger.info("ingest %s — starting", scope)
            batch = await connector.ingest(account_id=account_id)
            if batch.has_writes():
                logger.info(
                    "ingest %s — applying %d entities, %d metadata patches, %d persons, %d edges",
                    scope,
                    len(batch.entities),
                    len(batch.metadata_patches),
                    len(batch.persons),
                    len(batch.edges),
                )
                await upsert_batch(batch)
                logger.info("ingest %s — complete in %.1fs", scope, perf_counter() - scope_started)
            else:
                logger.info("ingest %s — no data returned", scope)
    except Exception:
        logger.exception("ingest failed for connector %s", source)
    finally:
        logger.debug("ingest %s total elapsed %.1fs", source, perf_counter() - started)


def setup_sync(
    scheduler: AsyncIOScheduler,
    *,
    poll_interval_seconds: float | None = None,
) -> None:
    """Register scheduled poll jobs, optionally overriding connector intervals."""
    from agentgraph.connectors.registry import get_all_connectors

    if poll_interval_seconds == 0:
        logger.info("Background connector polling is disabled by configuration")
        return

    for connector in get_all_connectors():
        interval = (
            timedelta(seconds=poll_interval_seconds)
            if poll_interval_seconds is not None
            else connector.poll_interval
        )
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
