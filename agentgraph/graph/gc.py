"""Garbage collection: remove entities not accessed within retention window."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import logging

from agentgraph.config import get_settings
from agentgraph.db.connection import get_pool

logger = logging.getLogger(__name__)


async def run_gc() -> int:
    """
    Delete entities where last_accessed < now() - retention_days.
    Edges are removed via ON DELETE CASCADE.
    Person entities with no remaining edges are pruned separately.
    Returns the total number of rows deleted.
    """
    settings = get_settings()
    pool = await get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Delete stale entities (edges cascade automatically)
            entity_count: int = await conn.fetchval(
                """
                WITH deleted AS (
                    DELETE FROM entities
                    WHERE last_accessed < now() - ($1 || ' days')::interval
                    RETURNING id
                )
                SELECT count(*) FROM deleted
                """,
                str(settings.retention_days),
            )

            # Delete persons with no remaining edges
            person_count: int = await conn.fetchval(
                """
                WITH deleted AS (
                    DELETE FROM persons p
                    WHERE NOT EXISTS (
                        SELECT 1 FROM edges e
                        WHERE e.source_person_id = p.id
                           OR e.target_person_id = p.id
                    )
                    AND last_accessed < now() - ($1 || ' days')::interval
                    RETURNING id
                )
                SELECT count(*) FROM deleted
                """,
                str(settings.retention_days),
            )

    total = entity_count + person_count
    logger.info(
        "GC complete: removed %d entities, %d persons (%d total, retention=%d days)",
        entity_count,
        person_count,
        total,
        settings.retention_days,
    )
    return total
