"""Connector fetch trigger — shared by CLI, MCP, and server API."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

from typing import Any

from agentgraph.connectors.base import ResourceType
from agentgraph.db.connection import get_pool


async def fetch_entity(platform: str, resource_id: str) -> dict[str, Any]:
    """Trigger a connector fetch for a known platform entity.

    Resolves the entity type from the DB (falling back to Document), resets
    synced_at so the connector treats the entity as stale, and runs a targeted
    fetch.  Returns counts of ingested entities/persons/edges.
    """
    from agentgraph.connectors.registry import get_connector

    connector = get_connector(platform)
    if connector is None:
        raise ValueError(f"No connector registered for platform '{platform}'")

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT entity_type FROM entities WHERE platform = $1 AND platform_entity_id = $2",
            platform,
            resource_id,
        )

    resource_type_map: dict[str, ResourceType] = {
        "Document": "document",
        "Spreadsheet": "spreadsheet",
        "Channel": "channel",
        "Message": "message",
        "Thread": "thread",
    }
    entity_type = row["entity_type"] if row else "Document"
    resource_type: ResourceType = resource_type_map.get(entity_type, "document")

    # Discord messages: fetch the parent channel
    if platform == "discord" and entity_type == "Message" and ":" in resource_id:
        resource_id = resource_id.split(":")[0]
        resource_type = "channel"

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE entities SET synced_at = NULL WHERE platform = $1 AND platform_entity_id = $2",
            platform,
            resource_id,
        )

    batch = await connector.fetch(resource_type=resource_type, resource_id=resource_id)
    return {
        "entities": len(batch.entities),
        "persons": len(batch.persons),
        "edges": len(batch.edges),
    }


async def fetch_entity_by_id(entity_id: str) -> dict[str, Any]:
    """Trigger a connector fetch for an entity identified by its internal UUID.

    Looks up platform and platform_entity_id from the DB, then delegates to
    fetch_entity.  Raises ValueError if the entity is not found.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT platform, platform_entity_id FROM entities WHERE id = $1::uuid",
            entity_id,
        )

    if row is None:
        raise ValueError(f"Entity not found: {entity_id}")

    return await fetch_entity(platform=row["platform"], resource_id=row["platform_entity_id"])
