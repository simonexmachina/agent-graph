"""Tests for configuration loading."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from pydantic import ValidationError

import agentgraph.config as config

# conftest pins these so unit tests never reach a real server; clear them where the
# point of the test is what the shipped defaults are.
_TRANSPORT_ENV = ("AGENTGRAPH_QUERY_TRANSPORT", "AGENTGRAPH_SERVER_UDS_PATH")


def _use_shipped_transport_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _TRANSPORT_ENV:
        monkeypatch.delenv(name, raising=False)


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_shipped_transport_defaults(monkeypatch)
    s = config.Settings(_env_file=None)
    assert s.server_port == 8765
    assert s.observation_threshold_seconds == 3
    assert s.retention_days == 90
    assert s.embedding_model == "BAAI/bge-small-en-v1.5"
    assert s.embedding_dimensions == 384
    assert s.poll_interval_seconds is None
    assert s.query_transport == "auto"


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTGRAPH_SERVER_PORT", "9000")
    monkeypatch.setenv("AGENTGRAPH_OBSERVATION_THRESHOLD_SECONDS", "10")
    monkeypatch.setenv("AGENTGRAPH_POLL_INTERVAL_SECONDS", "120")
    s = config.Settings()
    assert s.server_port == 9000
    assert s.observation_threshold_seconds == 10
    assert s.poll_interval_seconds == 120


def test_legacy_duration_threshold_env_is_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTGRAPH_DWELL_THRESHOLD_SECONDS", "10")

    assert config.Settings(_env_file=None).observation_threshold_seconds == 10


def test_settings_accepts_canonical_observation_field_names() -> None:
    settings = config.Settings(
        observation_threshold_seconds=10,
        observation_poll_interval_seconds=2.5,
        _env_file=None,
    )

    assert settings.observation_threshold_seconds == 10
    assert settings.observation_poll_interval_seconds == 2.5


def test_observation_threshold_env_takes_precedence_over_legacy_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTGRAPH_DWELL_THRESHOLD_SECONDS", "10")
    monkeypatch.setenv("AGENTGRAPH_OBSERVATION_THRESHOLD_SECONDS", "20")

    assert config.Settings(_env_file=None).observation_threshold_seconds == 20


def test_poll_interval_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTGRAPH_POLL_INTERVAL_SECONDS", "0")

    assert config.Settings().poll_interval_seconds == 0


def test_config_dir_env_controls_default_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTGRAPH_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("AGENTGRAPH_BACKEND_SQLITE_PATH", raising=False)
    _use_shipped_transport_defaults(monkeypatch)
    reloaded = importlib.reload(config)
    try:
        settings = reloaded.Settings()
        assert tmp_path == reloaded.CONFIG_DIR
        assert tmp_path / "credentials.json" == reloaded.CREDENTIALS_FILE
        assert tmp_path / "config.yaml" == reloaded.CONFIG_YAML_FILE
        assert settings.backend_sqlite_path == str(tmp_path / "agentgraph.db")
        assert settings.log_file == tmp_path / "agentgraph.log"
        assert settings.embedding_cache_dir == tmp_path / "models"
        assert settings.server_uds_path == tmp_path / "agentgraph.sock"
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


def test_embedding_cache_dir_is_independent_of_tmpdir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model cache must not follow $TMPDIR, which FastEmbed would default to."""
    monkeypatch.setenv("TMPDIR", str(tmp_path / "temp"))

    cache_dir = config.Settings(_env_file=None).embedding_cache_dir

    assert cache_dir == config.get_config_paths()[0] / "models"
    assert tmp_path / "temp" not in cache_dir.parents


def test_embedding_cache_dir_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTGRAPH_EMBEDDING_CACHE_DIR", "/opt/models")

    assert config.Settings(_env_file=None).embedding_cache_dir == Path("/opt/models")


def test_query_transport_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTGRAPH_QUERY_TRANSPORT", "in-process")

    assert config.Settings(_env_file=None).query_transport == "in-process"


def test_query_transport_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTGRAPH_QUERY_TRANSPORT", "grpc")

    with pytest.raises(ValidationError):
        config.Settings(_env_file=None)


@pytest.mark.parametrize("value", ["", "none", "null", "NONE", "  "])
def test_server_uds_path_can_be_disabled(
    value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty or none/null socket path serves and queries over TCP only."""
    monkeypatch.setenv("AGENTGRAPH_SERVER_UDS_PATH", value)

    assert config.Settings(_env_file=None).server_uds_path is None


def test_server_uds_path_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTGRAPH_SERVER_UDS_PATH", "/tmp/custom.sock")

    assert config.Settings(_env_file=None).server_uds_path == Path("/tmp/custom.sock")


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
