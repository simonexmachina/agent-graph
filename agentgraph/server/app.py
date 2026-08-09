"""FastAPI application: browser extension intake and server lifecycle."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agentgraph.core.context import clear_backend, set_backend
from agentgraph.graph.gc import run_gc
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
    from agentgraph.config import get_settings
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
    _scheduler.add_job(run_gc, "cron", hour=3, minute=0, id="gc")
    setup_sync(_scheduler)
    _scheduler.start()

    logger.info("AgentGraph server started (backend=%s)", settings.backend)
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
    meta: dict[str, str] | None = None


@app.post("/report-dwell", status_code=202)
async def report_dwell(req: ReportDwellRequest) -> dict[str, Any]:
    """
    Receive an incremental dwell time report (either upon hitting the threshold
    or when a tab loses focus/closes). Records the cumulative dwell time in the
    database for ranking, and dispatches a background connector fetch if the
    dwell time meets the threshold.
    """
    from agentgraph.server.dwell import record_dwell_time

    result = await record_dwell_time(req.url, req.dwell_ms, req.meta)
    return result


@app.get("/viewer", include_in_schema=False)
async def viewer() -> FileResponse:
    """Serve the graph viewer HTML."""
    return FileResponse(str(_STATIC_DIR / "viewer.html"))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
