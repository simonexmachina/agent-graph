"""Tests for the core entity-type vocabulary and its resource-type mapping."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agentgraph.connectors.base import (
    ENTITY_TYPES,
    RESOURCE_TYPE_TO_ENTITY_TYPE,
    BaseConnector,
    EntityBatch,
    EntityRecord,
    ResourceType,
    SourceReference,
)


class _StubConnector(BaseConnector):
    source = "stub"

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
        _ = resource_type, resource_id, meta, account_id
        return EntityBatch()


@pytest.mark.parametrize("entity_type", ["Task", "Video"])
def test_entity_types_include_task_and_video(entity_type: str) -> None:
    assert entity_type in ENTITY_TYPES


@pytest.mark.parametrize(
    ("resource_type", "entity_type"),
    [("work-item", "Task"), ("video", "Video")],
)
def test_resource_type_round_trips_to_entity_type(resource_type: str, entity_type: str) -> None:
    connector = _StubConnector()

    assert RESOURCE_TYPE_TO_ENTITY_TYPE[resource_type] == entity_type
    assert connector.normalise_fetch_id("res-1", entity_type) == ("res-1", resource_type)


@pytest.mark.parametrize(
    ("resource_type", "entity_type"),
    [("work-item", "Task"), ("video", "Video")],
)
def test_add_stubs_from_creates_typed_stub_for_new_resource_types(
    resource_type: str,
    entity_type: str,
) -> None:
    batch = EntityBatch()
    entity = EntityRecord(
        entity_type="Message",
        platform="slack",
        platform_entity_id="msg-1",
        content="see https://example.test/resource/1 for detail",
    )
    reference = SourceReference(
        source="other",
        resource_type=resource_type,  # type: ignore[arg-type]
        resource_id="resource-1",
    )

    with patch("agentgraph.server.router.classify_url", return_value=reference):
        batch.add_stubs_from(entity)

    assert [(item.entity_type, item.is_stub) for item in batch.entities] == [(entity_type, True)]
    assert [edge.edge_type for edge in batch.edges] == ["references"]


@pytest.mark.asyncio
async def test_meta_exposes_task_and_video_entity_types() -> None:
    from agentgraph.server.meta_api import get_meta

    connector = MagicMock()
    connector.source = "stub"
    connector.url_patterns = []
    settings = MagicMock(observation_threshold_seconds=3)

    with (
        patch("agentgraph.connectors.registry.get_all_connectors", return_value=[connector]),
        patch("agentgraph.config.get_settings", return_value=settings),
    ):
        result = await get_meta(include_dynamic_url_patterns=False)

    entity_types: Any = result["entity_types"]
    assert "Task" in entity_types
    assert "Video" in entity_types
