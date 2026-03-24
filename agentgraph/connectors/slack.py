"""Slack connector (stub — implemented in agent-graph-og3t)."""

from __future__ import annotations

from agentgraph.connectors.base import BaseConnector, EntityBatch


class SlackConnector(BaseConnector):
    source = "slack"

    def can_handle(self, url: str) -> bool:
        return "app.slack.com" in url

    async def fetch(self, resource_type: str, resource_id: str) -> EntityBatch:
        raise NotImplementedError("Slack connector not yet implemented")
