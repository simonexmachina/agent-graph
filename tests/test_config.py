"""Tests for configuration loading."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import agentgraph.config as config


def test_defaults() -> None:
    s = config.Settings()
    assert s.server_port == 8765
    assert s.dwell_threshold_seconds == 3
    assert s.retention_days == 90
    assert s.embedding_model == "BAAI/bge-small-en-v1.5"
    assert s.embedding_dimensions == 384


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTGRAPH_SERVER_PORT", "9000")
    monkeypatch.setenv("AGENTGRAPH_DWELL_THRESHOLD_SECONDS", "10")
    s = config.Settings()
    assert s.server_port == 9000
    assert s.dwell_threshold_seconds == 10


def test_config_dir_env_controls_default_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTGRAPH_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("AGENTGRAPH_BACKEND_SQLITE_PATH", raising=False)
    reloaded = importlib.reload(config)
    try:
        settings = reloaded.Settings()
        assert tmp_path == reloaded.CONFIG_DIR
        assert tmp_path / "credentials.json" == reloaded.CREDENTIALS_FILE
        assert tmp_path / "config.yaml" == reloaded.CONFIG_YAML_FILE
        assert settings.backend_sqlite_path == str(tmp_path / "agentgraph.db")
        env_files = settings.model_config["env_file"]
        assert env_files == [str(tmp_path / ".env"), ".env"]
    finally:
        monkeypatch.delenv("AGENTGRAPH_CONFIG_DIR", raising=False)
        importlib.reload(config)


def test_explicit_sqlite_path_overrides_config_dir_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit_db = tmp_path / "custom.db"
    monkeypatch.setenv("AGENTGRAPH_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("AGENTGRAPH_BACKEND_SQLITE_PATH", str(explicit_db))
    reloaded = importlib.reload(config)
    try:
        settings = reloaded.Settings()
        assert settings.backend_sqlite_path == str(explicit_db)
    finally:
        monkeypatch.delenv("AGENTGRAPH_CONFIG_DIR", raising=False)
        monkeypatch.delenv("AGENTGRAPH_BACKEND_SQLITE_PATH", raising=False)
        importlib.reload(config)


def test_config_dir_is_resolved_after_module_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "agentgraph"
    config_dir.mkdir()
    (config_dir / ".env").write_text("AGENTGRAPH_SERVER_PORT=9123\n", encoding="utf-8")
    monkeypatch.setenv("AGENTGRAPH_CONFIG_DIR", str(config_dir))
    monkeypatch.delenv("AGENTGRAPH_BACKEND_SQLITE_PATH", raising=False)

    settings = config.Settings()
    resolved_dir, config_file, _, _, database_file = config.get_config_paths()

    assert resolved_dir == config_dir
    assert config_file == config_dir / "config.toml"
    assert settings.server_port == 9123
    assert settings.backend_sqlite_path == str(database_file)


def test_memory_sqlite_path_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTGRAPH_BACKEND_SQLITE_PATH", ":memory:")
    assert config.Settings().backend_sqlite_path == ":memory:"


def test_config_dir_can_come_from_project_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "dotenv-config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENTGRAPH_CONFIG_DIR", raising=False)
    (tmp_path / ".env").write_text(
        f"AGENTGRAPH_CONFIG_DIR={config_dir}\n",
        encoding="utf-8",
    )

    resolved_dir, _, _, _, database_file = config.get_config_paths()

    assert resolved_dir == config_dir
    assert database_file == config_dir / "agentgraph.db"
