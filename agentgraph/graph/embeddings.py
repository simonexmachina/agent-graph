"""Embedding model: load once, encode on demand."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, cast

import numpy as np
from fastembed import TextEmbedding
from numpy.typing import NDArray

from agentgraph.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_model() -> TextEmbedding:
    settings = get_settings()
    logger.info("Loading embedding model: %s", settings.embedding_model)
    return TextEmbedding(model_name=settings.embedding_model)


def encode(text: str) -> list[float]:
    """Return a normalized embedding vector for the given text."""
    model = _get_model()
    vec = cast(NDArray[Any], next(iter(model.embed([text]))))
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec = vec / norm
    return [float(value) for value in vec.tolist()]
