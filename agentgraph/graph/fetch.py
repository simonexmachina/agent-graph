"""Connector fetch trigger — shared by CLI, MCP, and server API."""

from __future__ import annotations

from typing import Any

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

    resource_type_map = {
        "Document": "document",
        "Spreadsheet": "spreadsheet",
        "Channel": "channel",
        "Message": "message",
        "Thread": "thread",
    }
    entity_type = row["entity_type"] if row else "Document"
    resource_type = resource_type_map.get(entity_type, "document")

    # Discord messages: fetch the parent channel
    if platform == "discord" and entity_type == "Message" and ":" in resource_id:
        resource_id = resource_id.split(":")[0]
        resource_type = "channel"

    # Gmail: trigger a full inbox scan
    if platform == "gmail":
        resource_id = "0"
        resource_type = "inbox"

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
