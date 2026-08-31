"""Tests for feed connector mutation notifications."""

from __future__ import annotations

from datetime import timedelta
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agentgraph.connectors.base import (
    EntityBatch,
    FetchPolicy,
    ResourceType,
    SourceReference,
)
from agentgraph.connectors.feed import (
    BookmarkMutation,
    FeedConnector,
    MutationEvent,
    MutationTarget,
    ObservationMutation,
    notify_feed_connectors,
    suppress_feed_notifications,
)
from agentgraph.core.context import set_backend


class _RecordingFeedConnector(FeedConnector):
    source: ClassVar[str] = "recording-feed"
    fetch_policy: ClassVar[FetchPolicy] = FetchPolicy(stale_after_seconds=60)
    poll_interval: ClassVar[timedelta | None] = timedelta(minutes=1)
    appears_in_auth_status: ClassVar[bool] = False

    def __init__(self) -> None:
        self.events: list[MutationEvent] = []

    def can_handle(self, url: str) -> bool:
        _ = url
        return False

    async def fetch(
        self,
        resource_type: ResourceType,
        resource_id: str,
        meta: dict[str, str] | None = None,
        account_id: str | None = None,
    ) -> EntityBatch:
        _ = (resource_type, resource_id, meta, account_id)
        return EntityBatch()

    async def publish_mutation(self, event: MutationEvent) -> None:
        self.events.append(event)


def _bookmark_event() -> BookmarkMutation:
    return BookmarkMutation(
        target=MutationTarget(
            platform="web",
            platform_entity_id="https://example.com",
            entity_type="Document",
            resource_type="document",
            url="https://example.com",
        ),
        bookmarked=True,
    )


@pytest.mark.asyncio
async def test_notifies_installed_feed_connectors() -> None:
    connector = _RecordingFeedConnector()
    event = _bookmark_event()

    with patch("agentgraph.connectors.registry.get_all_connectors", return_value=[connector]):
        await notify_feed_connectors(event)

    assert connector.events == [event]


@pytest.mark.asyncio
async def test_suppression_prevents_notification() -> None:
    connector = _RecordingFeedConnector()

    with (
        patch("agentgraph.connectors.registry.get_all_connectors", return_value=[connector]),
        suppress_feed_notifications(),
    ):
        await notify_feed_connectors(_bookmark_event())

    assert connector.events == []


@pytest.mark.asyncio
async def test_connector_failure_does_not_escape() -> None:
    connector = _RecordingFeedConnector()

    async def fail(_: MutationEvent) -> None:
        raise RuntimeError("feed unavailable")

    connector.publish_mutation = fail  # type: ignore[method-assign]
    with patch("agentgraph.connectors.registry.get_all_connectors", return_value=[connector]):
        await notify_feed_connectors(_bookmark_event())


def _entity(*, bookmarked: bool = False) -> dict[str, object]:
    return {
        "id": str(uuid4()),
        "entity_type": "Document",
        "platform": "web",
        "platform_entity_id": "https://example.com",
        "metadata": {"web_url": "https://example.com"},
        "bookmarked": bookmarked,
    }


@pytest.mark.asyncio
async def test_bookmark_change_notifies_after_storage_update() -> None:
    from agentgraph.graph.bookmark import set_entity_bookmark

    entity = _entity()
    updated = {**entity, "bookmarked": True}
    backend = MagicMock()
    backend.get_entities_by_id_prefix = AsyncMock(return_value=[entity])
    backend.set_entity_bookmarked = AsyncMock(return_value=updated)
    set_backend(backend)

    with patch(
        "agentgraph.connectors.feed.notify_feed_connectors", new=AsyncMock()
    ) as notify:
        await set_entity_bookmark(str(entity["id"])[:8], True)

    backend.set_entity_bookmarked.assert_awaited_once()
    await_args = notify.await_args
    assert await_args is not None
    event = await_args.args[0]
    assert isinstance(event, BookmarkMutation)
    assert event.bookmarked is True


@pytest.mark.asyncio
async def test_bookmark_noop_does_not_notify() -> None:
    from agentgraph.graph.bookmark import set_entity_bookmark

    entity = _entity(bookmarked=True)
    backend = MagicMock()
    backend.get_entities_by_id_prefix = AsyncMock(return_value=[entity])
    backend.set_entity_bookmarked = AsyncMock()
    set_backend(backend)

    with patch(
        "agentgraph.connectors.feed.notify_feed_connectors", new=AsyncMock()
    ) as notify:
        await set_entity_bookmark(str(entity["id"])[:8], True)

    backend.set_entity_bookmarked.assert_not_awaited()
    notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_duration_increment_notifies_after_storage_update() -> None:
    from agentgraph.server.observation import record_observation

    backend = MagicMock()
    backend.increment_observation_duration = AsyncMock()
    set_backend(backend)
    reference = SourceReference(
        source="gmail",
        resource_type="thread",
        resource_id="thread-1",
    )

    with (
        patch(
            "agentgraph.server.observation.classify_observation_url",
            new=AsyncMock(return_value=reference),
        ),
        patch(
            "agentgraph.connectors.feed.notify_feed_connectors", new=AsyncMock()
        ) as notify,
    ):
        await record_observation(
            "https://mail.google.com/thread-1",
            3_000,
            "observation-1",
            False,
        )

    backend.increment_observation_duration.assert_awaited_once()
    await_args = notify.await_args
    assert await_args is not None
    event = await_args.args[0]
    assert isinstance(event, ObservationMutation)
    assert event.observation_duration_ms == 3_000


@pytest.mark.asyncio
async def test_duplicate_observation_does_not_notify() -> None:
    from agentgraph.server.observation import record_observation

    backend = MagicMock()
    backend.observation_exists = AsyncMock(return_value=True)
    set_backend(backend)
    reference = SourceReference(
        source="gmail",
        resource_type="thread",
        resource_id="thread-1",
    )

    with (
        patch(
            "agentgraph.server.observation.classify_observation_url",
            new=AsyncMock(return_value=reference),
        ),
        patch(
            "agentgraph.connectors.feed.notify_feed_connectors", new=AsyncMock()
        ) as notify,
    ):
        await record_observation(
            "https://mail.google.com/thread-1",
            3_000,
            "observation-1",
            True,
        )

    notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_delete_notifies_after_storage_update() -> None:
    from agentgraph.connectors.feed import TombstoneMutation
    from agentgraph.graph.delete import delete_entity

    entity = _entity()
    backend = MagicMock()
    backend.get_entities_by_id_prefix = AsyncMock(return_value=[entity])
    backend.delete_entity = AsyncMock(return_value=entity)
    set_backend(backend)

    with patch(
        "agentgraph.connectors.feed.notify_feed_connectors", new=AsyncMock()
    ) as notify:
        await delete_entity(str(entity["id"])[:8])

    backend.delete_entity.assert_awaited_once()
    await_args = notify.await_args
    assert await_args is not None
    assert isinstance(await_args.args[0], TombstoneMutation)
