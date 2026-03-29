"""asyncpg connection pool management."""

# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportInvalidTypeArguments=false

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import asyncpg

from agentgraph.config import get_settings

_pool: asyncpg.Pool | None = None  # type: ignore[type-arg]

SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text()
MIGRATE_V2_SQL = (Path(__file__).parent / "migrate_v2.sql").read_text()


async def get_pool() -> asyncpg.Pool:  # type: ignore[type-arg]
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
    assert _pool is not None
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def apply_schema() -> None:
    """Create tables and indexes if they don't exist, then run migrations."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
        await conn.execute(MIGRATE_V2_SQL)


async def acquire() -> AsyncGenerator[Any, None]:
    """Async context manager that yields a connection from the pool."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn
