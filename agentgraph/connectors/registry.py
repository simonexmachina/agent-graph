"""Connector registry: maps source names to connector instances.

Built-in connectors are discovered via Python entry points
(``agentgraph.connectors`` group). Third-party connectors can be installed
as separate packages that declare the same entry point group.
"""

from __future__ import annotations

import importlib.metadata
import logging
from collections.abc import Iterable

from agentgraph.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_registry: dict[str, BaseConnector] = {}
_entry_points: dict[str, importlib.metadata.EntryPoint] = {}
_bootstrapped = False


def register(connector: BaseConnector) -> None:
    _registry[connector.source] = connector


def get_connector(source: str) -> BaseConnector | None:
    bootstrap()
    if source not in _registry and source in _entry_points:
        _load_entry_point(source, _entry_points[source])
    return _registry.get(source)


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
        logger.debug("Loaded connector %r from %s", ep.name, ep.value)
        if connector.source != name:
            _entry_points.pop(name, None)
    except Exception as exc:
        _entry_points.pop(name, None)
        logger.warning("Failed to load connector %r: %s", ep.name, exc)
