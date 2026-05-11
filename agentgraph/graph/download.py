"""Authenticated source-file downloads for graph entities."""

from __future__ import annotations

from typing import Any

from agentgraph.graph.query import get_entity


async def download_entity(entity_ref: str, output_path: str | None = None) -> dict[str, Any]:
    """Download an entity's source file using its connector's stored auth."""
    from agentgraph.connectors.registry import bootstrap, get_connector

    entity = await get_entity(entity_ref)
    if entity is None:
        raise ValueError(f"Entity not found: {entity_ref}")

    platform = str(entity["platform"])
    platform_entity_id = str(entity["platform_entity_id"])
    entity_type = str(entity["entity_type"])

    bootstrap()
    connector = get_connector(platform)
    if connector is None:
        raise ValueError(f"No connector registered for platform '{platform}'")

    resource_id, resource_type = connector.normalise_fetch_id(platform_entity_id, entity_type)
    try:
        return await connector.download(
            resource_type=resource_type,
            resource_id=resource_id,
            output_path=output_path,
        )
    except NotImplementedError as exc:
        raise ValueError(str(exc)) from exc
