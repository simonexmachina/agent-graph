"""Tests for server lifecycle background work."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from agentgraph.server import app as server_app


@pytest.mark.asyncio
async def test_embedding_model_preload_runs_off_event_loop() -> None:
    calling_thread: int | None = None

    def load_model() -> None:
        nonlocal calling_thread
        calling_thread = threading.get_ident()

    with patch.object(server_app, "_load_embedding_model", side_effect=load_model):
        await server_app._preload_embedding_model()

    assert calling_thread is not None
    assert calling_thread != threading.get_ident()


@pytest.mark.asyncio
async def test_embedding_model_preload_failure_is_non_fatal(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        patch.object(server_app, "_load_embedding_model", side_effect=RuntimeError("broken")),
        caplog.at_level(logging.ERROR),
    ):
        await server_app._preload_embedding_model()

    assert "Failed to preload embedding model" in caplog.text


@pytest.mark.asyncio
async def test_lifespan_does_not_wait_for_embedding_model_preload() -> None:
    preload_started = asyncio.Event()
    allow_preload_to_finish = asyncio.Event()

    async def preload_embedding_model() -> None:
        preload_started.set()
        await allow_preload_to_finish.wait()

    @asynccontextmanager
    async def backend_context() -> AsyncGenerator[None, None]:
        yield

    scheduler = MagicMock()
    settings = MagicMock(
        backend="sqlite",
        log_level="INFO",
        log_file=None,
        poll_interval_seconds=300,
        server_host="127.0.0.1",
        server_port=8765,
    )

    with (
        patch.object(server_app, "backend_context", backend_context),
        patch.object(server_app, "_preload_embedding_model", preload_embedding_model),
        patch.object(server_app, "AsyncIOScheduler", return_value=scheduler),
        patch.object(server_app, "setup_sync"),
        patch.object(server_app, "shutdown_poll_tasks", new=AsyncMock()),
        patch("agentgraph.config.get_config_paths", return_value=(MagicMock(), MagicMock())),
        patch("agentgraph.config.get_settings", return_value=settings),
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.logging.configure_logging"),
    ):
        context = server_app.lifespan(FastAPI())
        await context.__aenter__()
        await asyncio.wait_for(preload_started.wait(), timeout=1)

        assert not allow_preload_to_finish.is_set()

        allow_preload_to_finish.set()
        await context.__aexit__(None, None, None)
