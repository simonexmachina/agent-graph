"""Tests for embedding generation."""

from __future__ import annotations

import importlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from agentgraph.graph import embeddings


def _fake_settings() -> SimpleNamespace:
    return SimpleNamespace(embedding_model="test/model", embedding_cache_dir=Path("/cache/models"))


class FakeTextEmbedding:
    model_names: list[str] = []
    cache_dirs: list[str] = []
    passage_calls: list[list[str]] = []
    query_calls: list[str] = []

    def __init__(self, model_name: str, cache_dir: str) -> None:
        self.model_names.append(model_name)
        self.cache_dirs.append(cache_dir)

    def passage_embed(self, documents: list[str]) -> list[np.ndarray[Any, np.dtype[np.float32]]]:
        self.passage_calls.append(documents)
        return [np.array([3.0, 4.0], dtype=np.float32)]

    def query_embed(self, query: str) -> list[np.ndarray[Any, np.dtype[np.float32]]]:
        self.query_calls.append(query)
        return [np.array([5.0, 12.0], dtype=np.float32)]


def test_encode_passage_uses_configured_fastembed_model_and_normalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeTextEmbedding.model_names = []
    FakeTextEmbedding.cache_dirs = []
    FakeTextEmbedding.passage_calls = []
    FakeTextEmbedding.query_calls = []
    embeddings_module = importlib.reload(embeddings)
    monkeypatch.setattr(embeddings_module, "TextEmbedding", FakeTextEmbedding)
    monkeypatch.setattr(embeddings_module, "get_settings", _fake_settings)

    try:
        encoded = embeddings_module.encode_passage("hello")

        assert len(encoded) == 2
        assert abs(encoded[0] - 0.6) < 1e-6
        assert abs(encoded[1] - 0.8) < 1e-6
        assert FakeTextEmbedding.model_names == ["test/model"]
        assert FakeTextEmbedding.cache_dirs == ["/cache/models"]
        assert FakeTextEmbedding.passage_calls == [["hello"]]
        assert FakeTextEmbedding.query_calls == []
    finally:
        importlib.reload(embeddings_module)


def test_encode_query_uses_fastembed_query_path_and_normalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeTextEmbedding.model_names = []
    FakeTextEmbedding.cache_dirs = []
    FakeTextEmbedding.passage_calls = []
    FakeTextEmbedding.query_calls = []
    embeddings_module = importlib.reload(embeddings)
    monkeypatch.setattr(embeddings_module, "TextEmbedding", FakeTextEmbedding)
    monkeypatch.setattr(embeddings_module, "get_settings", _fake_settings)

    try:
        encoded = embeddings_module.encode_query("needle")

        assert len(encoded) == 2
        assert abs(encoded[0] - (5.0 / 13.0)) < 1e-6
        assert abs(encoded[1] - (12.0 / 13.0)) < 1e-6
        assert FakeTextEmbedding.model_names == ["test/model"]
        assert FakeTextEmbedding.query_calls == ["needle"]
        assert FakeTextEmbedding.passage_calls == []
    finally:
        importlib.reload(embeddings_module)


def test_embedding_inference_is_serialized_across_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConcurrentTextEmbedding(FakeTextEmbedding):
        active = 0
        max_active = 0
        state_lock = threading.Lock()

        def passage_embed(
            self, documents: list[str]
        ) -> list[np.ndarray[Any, np.dtype[np.float32]]]:
            with self.state_lock:
                type(self).active += 1
                type(self).max_active = max(type(self).max_active, type(self).active)
            time.sleep(0.05)
            with self.state_lock:
                type(self).active -= 1
            return [np.array([3.0, 4.0], dtype=np.float32)]

    embeddings_module = importlib.reload(embeddings)
    monkeypatch.setattr(embeddings_module, "TextEmbedding", ConcurrentTextEmbedding)
    monkeypatch.setattr(embeddings_module, "get_settings", _fake_settings)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(embeddings_module.encode_passage, ["one", "two"]))

        assert all(
            abs(actual - expected) < 1e-6
            for actual, expected in zip(results[0], [0.6, 0.8], strict=True)
        )
        assert all(
            abs(actual - expected) < 1e-6
            for actual, expected in zip(results[1], [0.6, 0.8], strict=True)
        )
        assert ConcurrentTextEmbedding.max_active == 1
    finally:
        importlib.reload(embeddings_module)
