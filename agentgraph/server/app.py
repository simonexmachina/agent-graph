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
from agentgraph.core.context import set_backend
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
    from agentgraph.backends import get_backend_class
    from agentgraph.connectors.registry import bootstrap
    from agentgraph.logging import configure_logging

    settings = get_settings()
    configure_logging(settings.log_level)

    backend_class = get_backend_class(settings.backend)
    if settings.backend == "postgres":
        backend = backend_class(settings.database_url)
    elif settings.backend == "sqlite":
        backend = backend_class(settings.backend_sqlite_path, settings.backend_sqlite_vector_mode)
    else:
        backend = backend_class(settings)

    await backend.initialize()
    set_backend(backend)

    bootstrap()
    _dwell_task = asyncio.create_task(run_dwell_loop())

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(run_gc, "cron", hour=3, minute=0, id="gc")
    setup_sync(_scheduler)
    _scheduler.start()

    logger.info("AgentGraph server started (backend=%s)", settings.backend)
    yield

    if _dwell_task:
        _dwell_task.cancel()
    if _scheduler:
        _scheduler.shutdown(wait=False)
    await backend.close()
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
    import json as _json

    from agentgraph.core.context import get_backend

    logger.debug("observe: %s %s (tab %s)", event.type, event.url, event.tab_id)

    meta = event.meta if isinstance(event, FocusEvent) else None
    meta_json = _json.dumps(meta) if meta else None

    backend = get_backend()

    if meta_json:
        await backend.patch_observation_meta(
            event.type, event.tab_id, event.url, meta_json
        )

    await backend.insert_observation(
        event_type=event.type,
        url=event.url,
        title=event.title if isinstance(event, FocusEvent) else None,
        tab_id=event.tab_id,
        timestamp=event.timestamp,
        meta=meta_json,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
