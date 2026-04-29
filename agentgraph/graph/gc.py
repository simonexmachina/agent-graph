"""Garbage collection: remove entities not accessed within retention window."""

from __future__ import annotations

import logging

from agentgraph.config import get_settings
from agentgraph.core.context import get_backend

logger = logging.getLogger(__name__)


async def run_gc() -> int:
    """
    Delete entities where last_accessed < now() - retention_days.
    Edges are removed via ON DELETE CASCADE.
    Returns the total number of rows deleted.
    """
    settings = get_settings()
    total = await get_backend().gc_entities(settings.retention_days)
    logger.info(
        "GC complete: removed %d entities (retention=%d days)",
        total,
        settings.retention_days,
    )
    return total
