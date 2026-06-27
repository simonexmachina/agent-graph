"""Small performance instrumentation helpers."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import Any

logger = logging.getLogger("agentgraph.perf")


@contextmanager
def timed(operation: str, **fields: Any) -> Iterator[None]:
    """Log elapsed time for an operation at debug level."""
    start = perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (perf_counter() - start) * 1000
        suffix = " ".join(f"{key}={value}" for key, value in fields.items())
        if suffix:
            logger.debug("%s completed in %.1fms %s", operation, elapsed_ms, suffix)
        else:
            logger.debug("%s completed in %.1fms", operation, elapsed_ms)
