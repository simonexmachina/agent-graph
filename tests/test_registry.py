"""Tests for connector registry discovery and lazy loading."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from agentgraph.connectors.base import (
    BaseConnector,
    EntityBatch,
    EntityTypeDefinition,
    ResourceType,
)


class _LazyConnector(BaseConnector):
    source = "lazy"

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


class _OtherConnector(BaseConnector):
    source = "other"

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


class _FakeEntryPoint:
    def __init__(self, name: str, factory: Callable[[], type[BaseConnector]]) -> None:
        self.name = name
        self.value = f"tests:{name}"
        self._factory = factory
        self.loaded = False

    def load(self) -> type[BaseConnector]:
        self.loaded = True
        return self._factory()


def test_get_connector_lazily_loads_only_requested_entry_point(monkeypatch: Any) -> None:
    from agentgraph.connectors import registry

    lazy_ep = _FakeEntryPoint("lazy", lambda: _LazyConnector)
    other_ep = _FakeEntryPoint("other", lambda: _OtherConnector)
    monkeypatch.setattr(registry, "_registry", {})
    monkeypatch.setattr(registry, "_entry_points", {})
    monkeypatch.setattr(registry, "_bootstrapped", False)
    monkeypatch.setattr(registry, "_connector_entry_points", lambda: [lazy_ep, other_ep])

    connector = registry.get_connector("lazy")

    assert connector is not None
    assert connector.source == "lazy"
    assert lazy_ep.loaded is True
    assert other_ep.loaded is False


def test_get_all_connectors_loads_discovered_entry_points(monkeypatch: Any) -> None:
    from agentgraph.connectors import registry

    lazy_ep = _FakeEntryPoint("lazy", lambda: _LazyConnector)
    other_ep = _FakeEntryPoint("other", lambda: _OtherConnector)
    monkeypatch.setattr(registry, "_registry", {})
    monkeypatch.setattr(registry, "_entry_points", {})
    monkeypatch.setattr(registry, "_bootstrapped", False)
    monkeypatch.setattr(registry, "_connector_entry_points", lambda: [lazy_ep, other_ep])

    connectors = registry.get_all_connectors()

    assert {connector.source for connector in connectors} == {"lazy", "other"}
    assert lazy_ep.loaded is True
    assert other_ep.loaded is True


def test_get_connector_records_entry_point_load_error(monkeypatch: Any) -> None:
    from agentgraph.connectors import registry

    failing_ep = _FakeEntryPoint("broken", lambda: (_ for _ in ()).throw(ModuleNotFoundError("missing")))
    monkeypatch.setattr(registry, "_registry", {})
    monkeypatch.setattr(registry, "_entry_points", {})
    monkeypatch.setattr(registry, "_load_errors", {})
    monkeypatch.setattr(registry, "_bootstrapped", False)
    monkeypatch.setattr(registry, "_connector_entry_points", lambda: [failing_ep])

    assert registry.get_connector("broken") is None
    assert registry.get_connector_load_error("broken") == "missing"


def test_entity_type_names_are_shared_and_resource_types_are_connector_local(
    monkeypatch: Any,
) -> None:
    from agentgraph.connectors import registry

    class _FirstConnector(_LazyConnector):
        source = "first"
        entity_types = (
            EntityTypeDefinition(
                name="Project",
                resource_type="project",
                description="A project in the first source.",
            ),
        )

    class _SecondConnector(_LazyConnector):
        source = "second"
        entity_types = (
            EntityTypeDefinition(
                name="Project",
                resource_type="project",
                description="A project in the second source.",
            ),
        )

    connectors = [_SecondConnector(), _FirstConnector()]
    monkeypatch.setattr(registry, "_registry", {})
    for connector in connectors:
        registry.register(connector)

    names = registry.get_entity_type_names(connectors)
    catalog = dict(registry.get_entity_type_catalog(connectors))

    assert names == sorted(names)
    assert names.count("Project") == 1
    assert catalog["Project"] == [
        ("first", "A project in the first source."),
        ("second", "A project in the second source."),
    ]


@pytest.mark.parametrize(
    "entity_types",
    [
        (
            EntityTypeDefinition(name="Project", resource_type="project", description="One"),
            EntityTypeDefinition(name="Project", resource_type="portfolio", description="Two"),
        ),
        (
            EntityTypeDefinition(name="Project", resource_type="project", description="One"),
            EntityTypeDefinition(name="Portfolio", resource_type="project", description="Two"),
        ),
    ],
)
def test_register_rejects_duplicate_connector_entity_type_fields(
    monkeypatch: Any,
    entity_types: tuple[EntityTypeDefinition, ...],
) -> None:
    from agentgraph.connectors import registry

    class _InvalidConnector(_LazyConnector):
        source = "invalid"

    _InvalidConnector.entity_types = entity_types
    monkeypatch.setattr(registry, "_registry", {})

    with pytest.raises(ValueError, match="declares .* more than once"):
        registry.register(_InvalidConnector())
