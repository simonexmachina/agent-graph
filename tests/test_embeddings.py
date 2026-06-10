"""Tests for embedding generation."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from agentgraph.graph import embeddings


class FakeTextEmbedding:
    model_names: list[str] = []

    def __init__(self, model_name: str) -> None:
        self.model_names.append(model_name)

    def embed(self, documents: list[str]) -> list[np.ndarray[Any, np.dtype[np.float32]]]:
        assert documents == ["hello"]
        return [np.array([3.0, 4.0], dtype=np.float32)]


def test_encode_uses_configured_fastembed_model_and_normalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeTextEmbedding.model_names = []
    embeddings_module = importlib.reload(embeddings)
    monkeypatch.setattr(embeddings_module, "TextEmbedding", FakeTextEmbedding)
    monkeypatch.setattr(
        embeddings_module,
        "get_settings",
        lambda: SimpleNamespace(embedding_model="test/model"),
    )

    try:
        encoded = embeddings_module.encode("hello")

        assert len(encoded) == 2
        assert abs(encoded[0] - 0.6) < 1e-6
        assert abs(encoded[1] - 0.8) < 1e-6
        assert FakeTextEmbedding.model_names == ["test/model"]
    finally:
        importlib.reload(embeddings_module)
