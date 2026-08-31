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
    EntityUpdateMutation,
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


def _stored_entity(
    *,
    entity_id: str | None = None,
    entity_type: str = "Document",
    platform: str = "web",
    platform_entity_id: str = "https://example.com",
    title: str | None = "Example",
    content: str | None = "Example content",
) -> dict[str, object]:
    return {
        "id": entity_id or str(uuid4()),
        "entity_type": entity_type,
        "platform": platform,
        "platform_entity_id": platform_entity_id,
        "title": title,
        "content": content,
        "metadata": {"web_url": "https://example.com"},
        "created_at": "2026-08-31T00:00:00Z",
        "updated_at": "2026-08-31T00:00:01Z",
        "source_created_at": None,
        "source_updated_at": None,
        "synced_at": "2026-08-31T00:00:01Z",
        "observed_at": None,
        "retention_policy": "observed",
        "retention_parent_id": None,
        "cumulative_observation_duration_ms": 0,
        "bookmarked": False,
        "score": None,
    }


@pytest.mark.asyncio
async def test_changed_upsert_notifies_with_committed_entity_snapshot() -> None:
    from agentgraph.graph.upsert import upsert_batch

    entity = _stored_entity(content="Updated content")
    backend = MagicMock()
    backend.upsert_batch = AsyncMock(return_value=[entity])
    set_backend(backend)

    with (
        patch("agentgraph.graph.upsert._build_embeddings", return_value=({}, {})),
        patch("agentgraph.connectors.feed.notify_feed_connectors", new=AsyncMock()) as notify,
    ):
        await upsert_batch(EntityBatch())

    notify_args = notify.await_args
    assert notify_args is not None
    event = notify_args.args[0]
    assert isinstance(event, EntityUpdateMutation)
    assert event.target.platform == "web"
    assert event.entity.content == "Updated content"
    assert event.entity.updated_at == "2026-08-31T00:00:01Z"


@pytest.mark.asyncio
async def test_suppressed_changed_upsert_does_not_notify() -> None:
    from agentgraph.graph.upsert import upsert_batch

    connector = _RecordingFeedConnector()
    backend = MagicMock()
    backend.upsert_batch = AsyncMock(return_value=[_stored_entity()])
    set_backend(backend)

    with (
        patch("agentgraph.graph.upsert._build_embeddings", return_value=({}, {})),
        patch("agentgraph.connectors.registry.get_all_connectors", return_value=[connector]),
        suppress_feed_notifications(),
    ):
        await upsert_batch(EntityBatch())

    assert connector.events == []


@pytest.mark.asyncio
async def test_person_unification_notifies_primary_update_and_duplicate_tombstones() -> None:
    from agentgraph.connectors.feed import TombstoneMutation
    from agentgraph.graph.person import unify_persons

    primary = _stored_entity(
        entity_id="primary",
        entity_type="Person",
        platform="canonical",
        platform_entity_id="primary@example.com",
    )
    duplicate = _stored_entity(
        entity_id="duplicate",
        entity_type="Person",
        platform="canonical",
        platform_entity_id="duplicate@example.com",
    )
    updated = {**primary, "content": "Merged content"}
    backend = MagicMock()
    backend.merge_person_entities = AsyncMock(return_value=updated)
    set_backend(backend)

    with (
        patch("agentgraph.graph.person._resolve_person", side_effect=[primary, duplicate]),
        patch("agentgraph.connectors.feed.notify_feed_connectors", new=AsyncMock()) as notify,
    ):
        await unify_persons("primary", ["duplicate"])

    merge_args = backend.merge_person_entities.await_args
    assert merge_args is not None
    assert merge_args.args == ("primary", ["duplicate"])
    events = [call.args[0] for call in notify.await_args_list]
    assert isinstance(events[0], EntityUpdateMutation)
    assert events[0].entity.content == "Merged content"
    assert isinstance(events[1], TombstoneMutation)
    assert events[1].target.platform_entity_id == "duplicate@example.com"


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
