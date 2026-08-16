"""Generic execution of connector-owned command effects."""

from __future__ import annotations

from typing import Any

from agentgraph.connectors.base import ConnectorCommandEffects
from agentgraph.graph.delete import delete_platform_entity


async def execute_deletions(effects: ConnectorCommandEffects) -> list[dict[str, Any]]:
    """Delete connector-requested entities, ignoring ones already absent."""
    deleted: list[dict[str, Any]] = []
    for reference in effects.delete_entities:
        result = await delete_platform_entity(reference.platform, reference.platform_entity_id)
        if result is not None:
            deleted.append(result["entity"])
    return deleted
