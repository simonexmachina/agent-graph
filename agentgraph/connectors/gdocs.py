"""Google Docs connector (stub — implemented in agent-graph-f1bu)."""

from __future__ import annotations

from agentgraph.connectors.base import BaseConnector, EntityBatch


class GoogleDocsConnector(BaseConnector):
    source = "gdocs"

    def can_handle(self, url: str) -> bool:
        return "docs.google.com/document" in url

    async def fetch(self, resource_type: str, resource_id: str) -> EntityBatch:
        raise NotImplementedError("Google Docs connector not yet implemented")
