"""Connector fetch trigger — shared by CLI, MCP, and server API."""

from __future__ import annotations

from typing import Any

from agentgraph.connectors.base import ResourceType
from agentgraph.core.context import get_backend


async def fetch_entity(platform: str, resource_id: str) -> dict[str, Any]:
    """Trigger a connector fetch for a known platform entity.

    Resolves the entity type from the backend (falling back to Document), resets
    synced_at so the connector treats the entity as stale, and runs a targeted
    fetch.  Returns counts of ingested entities/persons/edges.
    """
    from agentgraph.connectors.registry import get_connector

    connector = get_connector(platform)
    if connector is None:
        raise ValueError(f"No connector registered for platform '{platform}'")

    backend = get_backend()
    entity_type = await backend.get_entity_type(platform, resource_id) or "Document"

    resource_type_map: dict[str, ResourceType] = {
        "Document": "document",
        "Folder": "folder",
        "Spreadsheet": "spreadsheet",
        "Channel": "channel",
        "Message": "message",
        "Thread": "thread",
    }
    resource_type: ResourceType = resource_type_map.get(entity_type, "document")

    # Discord messages: fetch the parent channel
    if platform == "discord" and entity_type == "Message" and ":" in resource_id:
        resource_id = resource_id.split(":")[0]
        resource_type = "channel"

    await backend.reset_synced_at(platform, resource_id)

    batch = await connector.fetch(resource_type=resource_type, resource_id=resource_id)
    return {
        "entities": len(batch.entities),
        "persons": len(batch.persons),
        "edges": len(batch.edges),
    }


async def fetch_entity_by_id(entity_id: str) -> dict[str, Any]:
    """Trigger a connector fetch for an entity identified by its internal UUID.

    Looks up platform and platform_entity_id from the backend, then delegates to
    fetch_entity.  Raises ValueError if the entity is not found.
    """
    ref = await get_backend().get_entity_platform_ref(entity_id)
    if ref is None:
        raise ValueError(f"Entity not found: {entity_id}")
    return await fetch_entity(platform=ref[0], resource_id=ref[1])
