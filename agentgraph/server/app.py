"""FastAPI application: observation event intake and lifecycle management."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Annotated, AsyncGenerator

from fastapi import FastAPI, Header, Response, status

from agentgraph.db.connection import apply_schema, close_pool, get_pool
from agentgraph.server.dwell import run_dwell_loop
from agentgraph.server.models import BlurEvent, FocusEvent

logger = logging.getLogger(__name__)

_dwell_task: asyncio.Task[None] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _dwell_task
    from agentgraph.connectors.registry import bootstrap

    await apply_schema()
    bootstrap()
    _dwell_task = asyncio.create_task(run_dwell_loop())
    logger.info("AgentGraph server started")
    yield
    if _dwell_task:
        _dwell_task.cancel()
    await close_pool()
    logger.info("AgentGraph server stopped")


app = FastAPI(title="AgentGraph", lifespan=lifespan)


@app.post("/observe", status_code=status.HTTP_204_NO_CONTENT)
async def observe(
    event: FocusEvent | BlurEvent,
    x_source_enabled: Annotated[str | None, Header()] = None,
) -> Response:
    """
    Receive a focus or blur observation from the browser extension.
    Persists immediately and returns 204 — no body.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO observations (event_type, url, title, tab_id, timestamp)
            VALUES ($1, $2, $3, $4, $5)
            """,
            event.type,
            event.url,
            event.title if isinstance(event, FocusEvent) else None,
            event.tab_id,
            event.timestamp,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
