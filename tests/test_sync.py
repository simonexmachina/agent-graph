"""Tests for background connector sync behaviour."""

from __future__ import annotations

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


def test_setup_sync_names_scheduler_jobs_with_connector_source() -> None:
    scheduler = MagicMock()

    with patch("agentgraph.connectors.registry.get_all_connectors", return_value=[_ScheduledConnector()]):
        sync.setup_sync(scheduler)

    scheduler.add_job.assert_called_once()
    _, _, kwargs = scheduler.add_job.mock_calls[0]
    assert kwargs["id"] == "sync_scheduled"
    assert kwargs["name"] == "poll connector scheduled"
