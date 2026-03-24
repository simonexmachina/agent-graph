"""Embedding model: load once, encode on demand."""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

from agentgraph.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    settings = get_settings()
    logger.info("Loading embedding model: %s", settings.embedding_model)
    return SentenceTransformer(settings.embedding_model)


def encode(text: str) -> list[float]:
    """Return a normalized embedding vector for the given text."""
    model = _get_model()
    vec: np.ndarray = model.encode(text, normalize_embeddings=True)  # type: ignore[assignment]
    return vec.tolist()  # type: ignore[no-any-return]
