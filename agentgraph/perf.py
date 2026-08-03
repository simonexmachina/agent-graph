"""Small performance instrumentation helpers."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from time import perf_counter
from typing import Any

logger = logging.getLogger("agentgraph.perf")

_timing_sink: ContextVar[list[tuple[str, float]] | None] = ContextVar("timing_sink", default=None)


@contextmanager
def capture_timings() -> Iterator[list[tuple[str, float]]]:
    """Collect nested ``timed`` spans for the current async task context."""
    timings: list[tuple[str, float]] = []
    token: Token[list[tuple[str, float]] | None] = _timing_sink.set(timings)
    try:
        yield timings
    finally:
        _timing_sink.reset(token)


@contextmanager
def timed(operation: str, **fields: Any) -> Iterator[None]:
    """Log elapsed time for an operation at debug level."""
    start = perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (perf_counter() - start) * 1000
        sink = _timing_sink.get()
        if sink is not None:
            sink.append((operation, elapsed_ms))
        suffix = " ".join(f"{key}={value}" for key, value in fields.items())
        if suffix:
            logger.debug("%s completed in %.1fms %s", operation, elapsed_ms, suffix)
        else:
            logger.debug("%s completed in %.1fms", operation, elapsed_ms)
