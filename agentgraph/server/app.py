"""FastAPI application: observation event intake and lifecycle management."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from fastapi import FastAPI, Header, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agentgraph.config import get_settings
from agentgraph.db.connection import apply_schema, close_pool, get_pool
from agentgraph.graph.gc import run_gc
from agentgraph.server.cli_api import router as cli_router
from agentgraph.server.dwell import run_dwell_loop
from agentgraph.server.graph_api import router as graph_router
from agentgraph.server.models import BlurEvent, FocusEvent
from agentgraph.server.sync import setup_sync

_STATIC_DIR = Path(__file__).parent / "static"

logger = logging.getLogger(__name__)

_dwell_task: asyncio.Task[None] | None = None
_scheduler: AsyncIOScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _dwell_task, _scheduler
    from agentgraph.connectors.registry import bootstrap
    from agentgraph.logging import configure_logging

    configure_logging(get_settings().log_level)
    await apply_schema()
    bootstrap()
    _dwell_task = asyncio.create_task(run_dwell_loop())

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(run_gc, "cron", hour=3, minute=0, id="gc")
    setup_sync(_scheduler)
    _scheduler.start()

    logger.info("AgentGraph server started")
    yield
    if _dwell_task:
        _dwell_task.cancel()
    if _scheduler:
        _scheduler.shutdown(wait=False)
    await close_pool()
    logger.info("AgentGraph server stopped")


app = FastAPI(title="AgentGraph", lifespan=lifespan)

app.include_router(graph_router)
app.include_router(cli_router)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/viewer", include_in_schema=False)
async def viewer() -> FileResponse:
    """Serve the graph viewer HTML."""
    return FileResponse(str(_STATIC_DIR / "viewer.html"))


@app.post("/observe", status_code=status.HTTP_204_NO_CONTENT)
async def observe(
    event: FocusEvent | BlurEvent,
    x_source_enabled: Annotated[str | None, Header()] = None,
) -> Response:
    """
    Receive a focus or blur observation from the browser extension.
    Persists immediately and returns 204 — no body.
    """
    logger.debug("observe: %s %s (tab %s)", event.type, event.url, event.tab_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        import json as _json
        meta = event.meta if isinstance(event, FocusEvent) else None
        meta_json = _json.dumps(meta) if meta else None

        # If this is a duplicate focus within the dedup window but carries meta
        # (content script fires ~300ms after the initial focus event), patch the
        # existing row rather than discarding the richer event.
        if meta_json:
            await conn.execute(
                """
                UPDATE observations SET meta = $1
                WHERE id = (
                    SELECT id FROM observations
                    WHERE event_type = $2
                      AND tab_id     = $3
                      AND url        = $4
                      AND timestamp  > now() - INTERVAL '5 seconds'
                    ORDER BY timestamp DESC
                    LIMIT 1
                ) AND meta IS NULL
                """,
                meta_json, event.type, event.tab_id, event.url,
            )

        await conn.execute(
            """
            INSERT INTO observations (event_type, url, title, tab_id, timestamp, meta)
            SELECT $1, $2, $3, $4, $5, $6
            WHERE NOT EXISTS (
                SELECT 1 FROM observations
                WHERE event_type = $1
                  AND tab_id     = $4
                  AND url        = $2
                  AND timestamp  > now() - INTERVAL '2 seconds'
            )
            """,
            event.type,
            event.url,
            event.title if isinstance(event, FocusEvent) else None,
            event.tab_id,
            event.timestamp,
            meta_json,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
