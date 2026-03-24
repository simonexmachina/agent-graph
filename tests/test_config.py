"""Tests for configuration loading."""

from __future__ import annotations

import os

import pytest

from agentgraph.config import Settings


def test_defaults() -> None:
    s = Settings()
    assert s.server_port == 8765
    assert s.dwell_threshold_seconds == 5
    assert s.retention_days == 90
    assert s.embedding_dimensions == 384


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTGRAPH_SERVER_PORT", "9000")
    monkeypatch.setenv("AGENTGRAPH_DWELL_THRESHOLD_SECONDS", "10")
    s = Settings()
    assert s.server_port == 9000
    assert s.dwell_threshold_seconds == 10


def test_database_url_default() -> None:
    s = Settings()
    assert "localhost" in s.database_url
    assert "agentgraph" in s.database_url
