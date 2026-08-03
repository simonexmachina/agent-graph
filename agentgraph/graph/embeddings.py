"""Embedding model: load once, encode on demand."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, cast

import numpy as np
from fastembed import TextEmbedding
from numpy.typing import NDArray

from agentgraph.config import get_settings
from agentgraph.perf import timed

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_model() -> TextEmbedding:
    settings = get_settings()
    logger.info("Loading embedding model: %s", settings.embedding_model)
    return TextEmbedding(model_name=settings.embedding_model)


def _normalise(vec: NDArray[Any]) -> list[float]:
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec = vec / norm
    return [float(value) for value in vec.tolist()]


def encode_passage(text: str) -> list[float]:
    """Return a normalized passage embedding vector for indexed content."""
    with timed("embedding.passage", characters=len(text)):
        model = _get_model()
        vec = cast(NDArray[Any], next(iter(model.passage_embed([text]))))
        return _normalise(vec)


def encode_query(text: str) -> list[float]:
    """Return a normalized query embedding vector for search text."""
    with timed("embedding.query", characters=len(text)):
        model = _get_model()
        vec = cast(NDArray[Any], next(iter(model.query_embed(text))))
        return _normalise(vec)


def encode(text: str) -> list[float]:
    """Return a normalized passage embedding vector for backwards compatibility."""
    return encode_passage(text)
