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
    EntityTypeDefinition,
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


class _ProjectConnector(_StubConnector):
    source = "projects"
    entity_types = (
        EntityTypeDefinition(
            name="Project",
            resource_type="project",
            description="A project tracked by this source.",
        ),
    )


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


def test_connector_entity_type_mapping_takes_precedence_over_core_mapping() -> None:
    class _PageConnector(_StubConnector):
        entity_types = (
            EntityTypeDefinition(
                name="Page",
                resource_type="document",
                description="A source-native page.",
            ),
        )

    connector = _PageConnector()

    assert connector.entity_type_for_resource_type("document") == "Page"
    assert connector.normalise_fetch_id("page-1", "Page") == ("page-1", "document")


def test_unknown_legacy_entity_type_keeps_document_fetch_fallback() -> None:
    assert _StubConnector().normalise_fetch_id("legacy-1", "LegacyType") == (
        "legacy-1",
        "document",
    )


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


def test_add_stubs_from_resolves_connector_local_resource_type() -> None:
    batch = EntityBatch()
    entity = EntityRecord(
        entity_type="Document",
        platform="source",
        platform_entity_id="doc-1",
        content="see https://projects.example/project/1",
    )
    reference = SourceReference(
        source="projects",
        resource_type="project",
        resource_id="project-1",
    )

    with (
        patch("agentgraph.server.router.classify_url", return_value=reference),
        patch(
            "agentgraph.connectors.registry.get_connector",
            return_value=_ProjectConnector(),
        ),
    ):
        batch.add_stubs_from(entity)

    assert [(item.entity_type, item.platform) for item in batch.entities] == [
        ("Project", "projects")
    ]


@pytest.mark.asyncio
async def test_meta_exposes_task_and_video_entity_types() -> None:
    from agentgraph.server.meta_api import get_meta

    connector = _ProjectConnector()
    settings = MagicMock(observation_threshold_seconds=3)

    with (
        patch("agentgraph.connectors.registry.get_all_connectors", return_value=[connector]),
        patch("agentgraph.config.get_settings", return_value=settings),
    ):
        result = await get_meta(include_dynamic_url_patterns=False)

    entity_types: Any = result["entity_types"]
    assert "Task" in entity_types
    assert "Video" in entity_types
    assert "Project" in entity_types
    assert entity_types == sorted(entity_types)
