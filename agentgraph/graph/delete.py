"""Delete graph entities."""

from __future__ import annotations

from typing import Any

from agentgraph.core.context import get_backend
from agentgraph.graph.query import get_entity


async def delete_entity(target: str) -> dict[str, Any]:
    """Delete an entity by UUID, UUID prefix, platform ref, or URL."""
    entity = await get_entity(target)
    if entity is None:
        raise ValueError(f"Entity {target!r} not found")
    deleted = await get_backend().delete_entity(entity["id"])
    return {"deleted": True, "entity": deleted}
