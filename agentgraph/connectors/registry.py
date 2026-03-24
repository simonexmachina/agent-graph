"""Connector registry: maps source names to connector instances."""

from __future__ import annotations

from agentgraph.connectors.base import BaseConnector

_registry: dict[str, BaseConnector] = {}


def register(connector: BaseConnector) -> None:
    _registry[connector.source] = connector


def get_connector(source: str) -> BaseConnector | None:
    return _registry.get(source)


def registered_sources() -> list[str]:
    return list(_registry.keys())


def bootstrap() -> None:
    """Register all built-in connectors. Called at server startup."""
    from agentgraph.connectors.gdocs import GoogleDocsConnector
    from agentgraph.connectors.slack import SlackConnector

    register(GoogleDocsConnector())
    register(SlackConnector())
