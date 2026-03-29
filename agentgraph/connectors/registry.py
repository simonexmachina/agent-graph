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


def get_all_connectors() -> list[BaseConnector]:
    return list(_registry.values())


def bootstrap() -> None:
    """Register all built-in connectors. Called at server startup."""
    from agentgraph.connectors.discord import DiscordConnector
    from agentgraph.connectors.gdocs import GoogleDocsConnector
    from agentgraph.connectors.gdrive import DriveChangesConnector
    from agentgraph.connectors.gmail import GmailConnector
    from agentgraph.connectors.gsheets import GoogleSheetsConnector
    from agentgraph.connectors.slack import SlackConnector

    register(GoogleDocsConnector())
    register(GoogleSheetsConnector())
    register(GmailConnector())
    register(SlackConnector())
    register(DiscordConnector())
    register(DriveChangesConnector())
