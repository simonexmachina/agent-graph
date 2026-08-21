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


async def execute_fetches(effects: ConnectorCommandEffects) -> list[dict[str, Any]]:
    """Fetch connector-owned references and persist their returned batches."""
    from agentgraph.connectors.registry import get_connector
    from agentgraph.graph.upsert import upsert_batch

    fetched: list[dict[str, Any]] = []
    for reference in effects.fetch_references:
        connector = get_connector(reference.source)
        if connector is None:
            raise ValueError(f"No connector registered for source {reference.source!r}")
        batch = await connector.fetch(
            resource_type=reference.resource_type,
            resource_id=reference.resource_id,
            meta=reference.fetch_meta,
        )
        if batch.entities or batch.persons or batch.edges:
            await upsert_batch(batch)
        fetched.append(
            {
                "source": reference.source,
                "resource_type": reference.resource_type,
                "resource_id": reference.resource_id,
                "entities": len(batch.entities),
                "persons": len(batch.persons),
                "edges": len(batch.edges),
            }
        )
    return fetched
