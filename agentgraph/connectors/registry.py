"""Connector registry: maps source names to connector instances.

Built-in connectors are discovered via Python entry points
(``agentgraph.connectors`` group). Third-party connectors can be installed
as separate packages that declare the same entry point group.
"""

from __future__ import annotations

import importlib.metadata
import logging

from agentgraph.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_registry: dict[str, BaseConnector] = {}


def register(connector: BaseConnector) -> None:
    _registry[connector.source] = connector


def get_connector(source: str) -> BaseConnector | None:
    return _registry.get(source)


def registered_sources() -> list[str]:
    return list(_registry.keys())


def get_all_connectors() -> list[BaseConnector]:
    return list(_registry.values())


def bootstrap() -> None:
    """Discover and register connectors via Python entry points."""
    for ep in importlib.metadata.entry_points(group="agentgraph.connectors"):
        try:
            connector_class: type[BaseConnector] = ep.load()
            register(connector_class())
            logger.debug("Loaded connector %r from %s", ep.name, ep.value)
        except Exception as exc:
            logger.warning("Failed to load connector %r: %s", ep.name, exc)

    if not _registry:
        logger.warning(
            "No connectors discovered. Install connector packages (e.g. pip install agentgraph[all]) "
            "or declare entry points in the 'agentgraph.connectors' group."
        )
