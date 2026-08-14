"""FastAPI application: browser extension intake and server lifecycle."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agentgraph.core.context import clear_backend, set_backend
from agentgraph.graph.expiration import run_expiration
from agentgraph.server.cli_api import router as cli_router
from agentgraph.server.graph_api import router as graph_router
from agentgraph.server.sync import setup_sync, shutdown_poll_tasks

_STATIC_DIR = Path(__file__).parent / "static"

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def viewer_url(host: str, port: int) -> str:
    browser_host = "127.0.0.1" if host in {"", "0.0.0.0", "::"} else host
    if ":" in browser_host and not browser_host.startswith("["):
        browser_host = f"[{browser_host}]"
    return f"http://{browser_host}:{port}/viewer"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _scheduler
    from agentgraph.backends import get_backend_class
    from agentgraph.config import get_config_paths, get_settings
    from agentgraph.connectors.registry import bootstrap
    from agentgraph.logging import configure_logging

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_file)

    backend_class: Any = get_backend_class(settings.backend)
    if settings.backend == "sqlite":
        backend = backend_class(settings.backend_sqlite_path, settings.backend_sqlite_vector_mode)
    else:
        backend = backend_class(settings)

    await backend.initialize()
    set_backend(backend)

    bootstrap()

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(run_expiration, "cron", hour=3, minute=0, id="expiration")
    setup_sync(_scheduler, poll_interval_seconds=settings.poll_interval_seconds)
    _scheduler.start()

    logger.info(
        "AgentGraph server started (backend=%s, config_dir=%s)",
        settings.backend,
        get_config_paths()[0],
    )
    logger.info("Web viewer: %s", viewer_url(settings.server_host, settings.server_port))
    yield

    if _scheduler:
        _scheduler.shutdown(wait=False)
    try:
        await shutdown_poll_tasks()
    finally:
        await backend.close()
        clear_backend()
    logger.info("AgentGraph server stopped")


app = FastAPI(title="AgentGraph", lifespan=lifespan)


@app.middleware("http")
async def log_request_timing(request: Request, call_next: Any) -> Any:
    start = perf_counter()
    response = await call_next(request)
    elapsed_ms = (perf_counter() - start) * 1000
    size = response.headers.get("content-length")
    logger.debug(
        "request %s %s -> %s in %.1fms%s",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        f" bytes={size}" if size else "",
    )
    return response

app.include_router(graph_router)
app.include_router(cli_router)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


class ReportDwellRequest(BaseModel):
    url: str
    dwell_ms: int
    observation_id: UUID
    observed: bool
    meta: dict[str, str] | None = None


class ExtensionPageRequest(BaseModel):
    url: str
    meta: dict[str, str] | None = None
    entity_id: str | None = None


class ExtensionBookmarkRequest(ExtensionPageRequest):
    bookmarked: bool


@app.post("/report-dwell", status_code=202)
async def report_dwell(req: ReportDwellRequest) -> dict[str, Any]:
    """
    Receive either the extension's one threshold-crossed observation event or a
    later dwell-only update. New observation IDs dispatch a fetch exactly once.
    """
    from agentgraph.server.dwell import record_dwell_time

    result = await record_dwell_time(
        req.url,
        req.dwell_ms,
        str(req.observation_id),
        req.observed,
        req.meta,
    )
    return result


@app.post("/api/extension/fetch")
async def extension_fetch(req: ExtensionPageRequest) -> dict[str, Any]:
    """Fetch the active browser URL through its connector."""
    from agentgraph.graph.fetch import fetch_url

    try:
        return await fetch_url(req.url, req.meta)
    except (ValueError, RuntimeError) as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/extension/page")
async def extension_page(req: ExtensionPageRequest) -> dict[str, Any]:
    """Return the existing graph entity for the active browser URL."""
    from agentgraph.server.cli_api import get_entity_by_url

    entity = await get_entity_by_url(req.url)
    return {"entity": entity}


@app.post("/api/extension/bookmark")
async def extension_bookmark(req: ExtensionBookmarkRequest) -> dict[str, Any]:
    """Set bookmark state for the active browser URL."""
    from agentgraph.graph.bookmark import set_entity_bookmark
    from agentgraph.graph.fetch import fetch_url
    from agentgraph.graph.query import get_entity_by_url

    try:
        entity = await get_entity_by_url(req.url)
        if entity is None and req.entity_id is not None:
            from agentgraph.graph.query import get_entity

            entity = await get_entity(req.entity_id)
        if entity is None and not req.bookmarked:
            raise ValueError("Page is not indexed")
        if entity is None:
            fetched = await fetch_url(req.url, req.meta)
            result = fetched.get("entity")
            if not isinstance(result, dict):
                raise ValueError("Page was fetched but no graph entity was created")
            result_id = result.get("id")
            if not isinstance(result_id, str):
                raise ValueError("Page was fetched but its graph entity has no valid ID")
            result = await set_entity_bookmark(result_id, True)
        else:
            result = await set_entity_bookmark(entity["id"], req.bookmarked)
        return {"entity": result}
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/viewer", include_in_schema=False)
async def viewer() -> FileResponse:
    """Serve the graph viewer HTML."""
    return FileResponse(str(_STATIC_DIR / "viewer.html"))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
