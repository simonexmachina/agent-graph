"""Tests for background connector sync behaviour."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentgraph.connectors.base import BaseConnector, EntityBatch, FetchPolicy, ResourceType
from agentgraph.server import sync


class _MissingAuthConnector(BaseConnector):
    source: ClassVar[str] = "missing"
    fetch_policy: ClassVar[FetchPolicy] = FetchPolicy(stale_after_seconds=60)
    poll_interval: ClassVar[timedelta | None] = timedelta(minutes=5)
    auth_label: ClassVar[str | None] = "missing"

    @classmethod
    def get_authenticated_user(cls) -> str | None:
        return None

    def can_handle(self, url: str) -> bool:
        return False

    async def fetch(
        self,
        resource_type: ResourceType,
        resource_id: str,
        meta: dict[str, str] | None = None,
        account_id: str | None = None,
    ) -> EntityBatch:
        return EntityBatch()

    async def poll(
        self,
        cursor: dict[str, Any],
        account_id: str | None = None,
    ) -> tuple[EntityBatch, dict[str, Any]]:
        raise AssertionError("missing-auth connector should not be polled")


class _FailingConnector(BaseConnector):
    source: ClassVar[str] = "failing"
    fetch_policy: ClassVar[FetchPolicy] = FetchPolicy(stale_after_seconds=60)
    appears_in_auth_status: ClassVar[bool] = False

    def can_handle(self, url: str) -> bool:
        return False

    async def fetch(
        self,
        resource_type: ResourceType,
        resource_id: str,
        meta: dict[str, str] | None = None,
        account_id: str | None = None,
    ) -> EntityBatch:
        return EntityBatch()

    async def poll(
        self,
        cursor: dict[str, Any],
        account_id: str | None = None,
    ) -> tuple[EntityBatch, dict[str, Any]]:
        raise RuntimeError("boom")


class _ScheduledConnector(BaseConnector):
    source: ClassVar[str] = "scheduled"
    fetch_policy: ClassVar[FetchPolicy] = FetchPolicy(stale_after_seconds=60)
    poll_interval: ClassVar[timedelta | None] = timedelta(seconds=30)
    appears_in_auth_status: ClassVar[bool] = False

    def can_handle(self, url: str) -> bool:
        return False

    async def fetch(
        self,
        resource_type: ResourceType,
        resource_id: str,
        meta: dict[str, str] | None = None,
        account_id: str | None = None,
    ) -> EntityBatch:
        return EntityBatch()


class _BlockingConnector(_ScheduledConnector):
    source: ClassVar[str] = "blocking"

    def __init__(self, started: asyncio.Event, cancelled: asyncio.Event) -> None:
        self._started = started
        self._cancelled = cancelled

    async def poll(
        self,
        cursor: dict[str, Any],
        account_id: str | None = None,
    ) -> tuple[EntityBatch, dict[str, Any]]:
        _ = (cursor, account_id)
        self._started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self._cancelled.set()
        raise AssertionError("blocking poll should be cancelled")


class _InvalidAuthConnector(_MissingAuthConnector):
    source: ClassVar[str] = "invalid"

    @classmethod
    def get_authenticated_user(cls) -> str | None:
        return "expired@example.com"

    @classmethod
    async def verify_auth(cls, account_id: str | None = None) -> tuple[str, str | None]:
        _ = account_id
        return ("invalid", "token expired")


class _IngestConnector(_ScheduledConnector):
    source: ClassVar[str] = "ingest"

    def __init__(self) -> None:
        self.accounts: list[str | None] = []

    def poll_account_ids(self) -> list[str | None]:
        return ["first@example.com", "second@example.com"]

    async def ingest(self, account_id: str | None = None) -> EntityBatch:
        self.accounts.append(account_id)
        return EntityBatch()


@pytest.fixture(autouse=True)
def clear_sync_backoff() -> None:
    sync.clear_poll_backoff()


@pytest.mark.asyncio
async def test_poll_connector_skips_missing_auth() -> None:
    backend = MagicMock()
    backend.load_cursor = AsyncMock()

    with patch("agentgraph.server.sync.get_backend", return_value=backend):
        await sync.poll_connector(_MissingAuthConnector())

    backend.load_cursor.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_connector_backs_off_after_failure() -> None:
    backend = MagicMock()
    backend.load_cursor = AsyncMock(return_value={})

    connector = _FailingConnector()
    with patch("agentgraph.server.sync.get_backend", return_value=backend):
        await sync.poll_connector(connector)
        await sync.poll_connector(connector)

    backend.load_cursor.assert_awaited_once()


@pytest.mark.asyncio
async def test_schedule_poll_connector_skips_when_already_running() -> None:
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def fake_poll_connector(connector: BaseConnector) -> None:
        _ = connector
        first_started.set()
        await release_first.wait()

    connector = _ScheduledConnector()
    with patch("agentgraph.server.sync.poll_connector", side_effect=fake_poll_connector) as poll:
        assert await sync.schedule_poll_connector(connector) == {
            "source": "scheduled",
            "status": "queued",
            "reason": None,
        }
        await first_started.wait()

        assert await sync.schedule_poll_connector(connector) == {
            "source": "scheduled",
            "status": "already_running",
            "reason": None,
        }

        release_first.set()
        await asyncio.sleep(0)

    assert poll.await_count == 1


@pytest.mark.asyncio
async def test_shutdown_poll_tasks_cancels_active_poll() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()
    backend = MagicMock()
    backend.load_cursor = AsyncMock(return_value={})
    backend.save_cursor = AsyncMock()

    connector = _BlockingConnector(started, cancelled)
    with patch("agentgraph.server.sync.get_backend", return_value=backend):
        task = asyncio.create_task(sync.poll_connector(connector))
        await started.wait()

        await sync.shutdown_poll_tasks(timeout=1)

    await cancelled.wait()
    assert task.done()
    assert task.cancelled()
    backend.save_cursor.assert_not_awaited()


@pytest.mark.asyncio
async def test_schedule_poll_connector_reports_missing_auth() -> None:
    with patch("agentgraph.server.sync.poll_connector", new=AsyncMock()) as poll:
        result = await sync.schedule_poll_connector(_MissingAuthConnector())

    assert result == {
        "source": "missing",
        "status": "skipped",
        "reason": "authentication missing",
    }
    poll.assert_not_called()


@pytest.mark.asyncio
async def test_schedule_poll_connector_reports_invalid_auth() -> None:
    with patch("agentgraph.server.sync.poll_connector", new=AsyncMock()) as poll:
        result = await sync.schedule_poll_connector(_InvalidAuthConnector())

    assert result == {
        "source": "invalid",
        "status": "skipped",
        "reason": "authentication invalid: token expired",
    }
    poll.assert_not_called()


@pytest.mark.asyncio
async def test_run_ingest_scopes_to_explicit_account() -> None:
    connector = _IngestConnector()

    await sync.run_ingest(connector, account_ids=["second@example.com"])

    assert connector.accounts == ["second@example.com"]


@pytest.mark.asyncio
async def test_run_ingest_uses_all_accounts_without_explicit_scope() -> None:
    connector = _IngestConnector()

    await sync.run_ingest(connector)

    assert connector.accounts == ["first@example.com", "second@example.com"]


def test_setup_sync_names_scheduler_jobs_with_connector_source() -> None:
    scheduler = MagicMock()

    with patch("agentgraph.connectors.registry.get_all_connectors", return_value=[_ScheduledConnector()]):
        sync.setup_sync(scheduler)

    scheduler.add_job.assert_called_once()
    _, _, kwargs = scheduler.add_job.mock_calls[0]
    assert kwargs["id"] == "sync_scheduled"
    assert kwargs["name"] == "poll connector scheduled"


def test_setup_sync_overrides_connector_interval() -> None:
    scheduler = MagicMock()

    with patch("agentgraph.connectors.registry.get_all_connectors", return_value=[_ScheduledConnector()]):
        sync.setup_sync(scheduler, poll_interval_seconds=120)

    args, kwargs = scheduler.add_job.call_args
    assert args[1] == "interval"
    assert kwargs["seconds"] == 120


def test_setup_sync_can_disable_polling() -> None:
    scheduler = MagicMock()

    with patch("agentgraph.connectors.registry.get_all_connectors") as get_connectors:
        sync.setup_sync(scheduler, poll_interval_seconds=0)

    get_connectors.assert_not_called()
    scheduler.add_job.assert_not_called()
