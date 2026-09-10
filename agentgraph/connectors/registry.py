"""Connector registry: maps source names to connector instances.

Built-in connectors are discovered via Python entry points
(``agentgraph.connectors`` group). Third-party connectors can be installed
as separate packages that declare the same entry point group.
"""

from __future__ import annotations

import importlib.metadata
import logging
from collections.abc import Iterable, Sequence
from typing import cast

from agentgraph.connectors.base import (
    ENTITY_TYPE_DESCRIPTIONS,
    ENTITY_TYPES,
    RESOURCE_TYPE_TO_ENTITY_TYPE,
    BaseConnector,
    EntityTypeDefinition,
    SourceReference,
)

logger = logging.getLogger(__name__)

_registry: dict[str, BaseConnector] = {}
_entry_points: dict[str, importlib.metadata.EntryPoint] = {}
_load_errors: dict[str, str] = {}
_bootstrapped = False


def register(connector: BaseConnector) -> None:
    _validate_entity_types(connector)
    _registry[connector.source] = connector


def _validate_entity_types(connector: BaseConnector) -> None:
    raw_definitions: object = getattr(type(connector), "entity_types", None)
    if not isinstance(raw_definitions, tuple):
        raise TypeError(f"Connector {connector.source!r} entity_types must be a tuple")
    definitions = cast(tuple[object, ...], raw_definitions)

    names: set[str] = set()
    resource_types: set[str] = set()
    for definition in definitions:
        if not isinstance(definition, EntityTypeDefinition):
            raise TypeError(
                f"Connector {connector.source!r} entity_types must contain "
                "EntityTypeDefinition values"
            )
        if definition.name in names:
            raise ValueError(
                f"Connector {connector.source!r} declares entity type "
                f"{definition.name!r} more than once"
            )
        if definition.resource_type in resource_types:
            raise ValueError(
                f"Connector {connector.source!r} declares resource type "
                f"{definition.resource_type!r} more than once"
            )
        names.add(definition.name)
        resource_types.add(definition.resource_type)


def get_entity_type_names(connectors: Sequence[BaseConnector] | None = None) -> list[str]:
    """Return the sorted union of core and installed connector entity type names."""
    resolved = list(connectors) if connectors is not None else get_all_connectors()
    names = set(ENTITY_TYPES)
    for connector in resolved:
        names.update(definition.name for definition in _entity_type_definitions(connector))
    return sorted(names)


def get_entity_type_catalog(
    connectors: Sequence[BaseConnector] | None = None,
) -> list[tuple[str, list[tuple[str, str]]]]:
    """Return entity types with their core or connector-labelled descriptions."""
    resolved = list(connectors) if connectors is not None else get_all_connectors()
    descriptions: dict[str, list[tuple[str, str]]] = {
        name: [("core", ENTITY_TYPE_DESCRIPTIONS[name])] for name in ENTITY_TYPES
    }
    for connector in resolved:
        for definition in _entity_type_definitions(connector):
            entries = descriptions.setdefault(definition.name, [])
            detail = (connector.source, definition.description)
            if detail not in entries:
                entries.append(detail)
    catalog: list[tuple[str, list[tuple[str, str]]]] = []
    for name in sorted(descriptions):
        entries = descriptions[name]
        entries.sort(key=lambda item: (item[0] != "core", item[0], item[1]))
        catalog.append((name, entries))
    return catalog


def _entity_type_definitions(connector: BaseConnector) -> tuple[EntityTypeDefinition, ...]:
    return cast(
        tuple[EntityTypeDefinition, ...],
        getattr(type(connector), "entity_types", ()),
    )


def entity_type_for_reference(reference: SourceReference) -> str:
    """Resolve a source-scoped resource type to the stored graph entity type."""
    connector = get_connector(reference.source)
    if connector is not None:
        return type(connector).entity_type_for_resource_type(reference.resource_type)
    try:
        return RESOURCE_TYPE_TO_ENTITY_TYPE[reference.resource_type]
    except KeyError as exc:
        raise ValueError(
            f"No connector registered for source {reference.source!r} and resource type "
            f"{reference.resource_type!r} is not a core resource type"
        ) from exc


def get_connector(source: str) -> BaseConnector | None:
    bootstrap()
    if source not in _registry and source in _entry_points:
        _load_entry_point(source, _entry_points[source])
    return _registry.get(source)


def get_connector_load_error(source: str) -> str | None:
    """Return the recorded entry-point import error for a connector, if any."""
    return _load_errors.get(source)


def registered_sources() -> list[str]:
    bootstrap()
    return list(dict.fromkeys([*_registry.keys(), *_entry_points.keys()]))


def get_all_connectors() -> list[BaseConnector]:
    bootstrap()
    for name, ep in list(_entry_points.items()):
        if name not in _registry:
            _load_entry_point(name, ep)
    return list(_registry.values())


def bootstrap() -> None:
    """Discover connector entry points without importing connector packages."""
    global _bootstrapped
    if _bootstrapped:
        return
    _bootstrapped = True

    for ep in _connector_entry_points():
        _entry_points.setdefault(ep.name, ep)

    if not _entry_points and not _registry:
        logger.warning(
            "No connectors discovered. Install connector packages (e.g. pip install agentgraph[all]) "
            "or declare entry points in the 'agentgraph.connectors' group."
        )


def _connector_entry_points() -> Iterable[importlib.metadata.EntryPoint]:
    return importlib.metadata.entry_points(group="agentgraph.connectors")


def _load_entry_point(name: str, ep: importlib.metadata.EntryPoint) -> None:
    try:
        connector_class: type[BaseConnector] = ep.load()
        connector = connector_class()
        register(connector)
        _load_errors.pop(name, None)
        logger.debug("Loaded connector %r from %s", ep.name, ep.value)
        if connector.source != name:
            _entry_points.pop(name, None)
    except Exception as exc:
        _entry_points.pop(name, None)
        _load_errors[name] = str(exc)
        logger.warning("Failed to load connector %r: %s", ep.name, exc)
