"""Application configuration loaded from environment variables and the config directory."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_config_dir() -> Path:
    raw = os.environ.get("AGENTGRAPH_CONFIG_DIR")
    if not raw:
        dotenv_value = dotenv_values(".env").get("AGENTGRAPH_CONFIG_DIR")
        raw = dotenv_value if isinstance(dotenv_value, str) else None
    return Path(raw).expanduser() if raw else Path.home() / ".agentgraph"


CONFIG_DIR = _default_config_dir()
CONFIG_FILE = CONFIG_DIR / "config.toml"
CONFIG_YAML_FILE = CONFIG_DIR / "config.yaml"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
DEFAULT_SQLITE_PATH = str(CONFIG_DIR / "agentgraph.db")
_INITIAL_CONFIG_DIR = CONFIG_DIR


def get_config_paths() -> tuple[Path, Path, Path, Path, Path]:
    """Return paths for the currently selected AgentGraph config directory.

    The module-level constants remain for compatibility, while this helper
    avoids stale paths when an embedding process sets the environment after
    importing AgentGraph.
    """
    config_dir = _default_config_dir()
    if config_dir == _INITIAL_CONFIG_DIR:
        return CONFIG_DIR, CONFIG_FILE, CONFIG_YAML_FILE, CREDENTIALS_FILE, Path(DEFAULT_SQLITE_PATH)
    # Keep direct constant overrides working for embedders and tests.
    if "AGENTGRAPH_CONFIG_DIR" not in os.environ and CONFIG_DIR != _INITIAL_CONFIG_DIR:
        return CONFIG_DIR, CONFIG_FILE, CONFIG_YAML_FILE, CREDENTIALS_FILE, Path(DEFAULT_SQLITE_PATH)
    return (
        config_dir,
        config_dir / "config.toml",
        config_dir / "config.yaml",
        config_dir / "credentials.json",
        config_dir / "agentgraph.db",
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTGRAPH_",
        # User-level config is loaded first;
        # project-local .env takes precedence.
        env_file=[str(CONFIG_DIR / ".env"), ".env"],
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Backend selection
    backend: str = Field(
        default="sqlite",
        description="Persistence backend: 'sqlite' | any installed plugin",
    )
    backend_sqlite_path: str = Field(
        default_factory=lambda: str(get_config_paths()[-1]),
        description="Path to SQLite database file (only used when backend='sqlite')",
    )
    backend_sqlite_vector_mode: str = Field(
        default="sqlite-vec",
        description="SQLite vector search mode: 'sqlite-vec' | 'numpy' | 'bm25-only'",
    )

    # Server
    server_host: str = Field(default="127.0.0.1")
    server_port: int = Field(default=8765)

    # Browser observation detection
    observation_threshold_seconds: int = Field(
        default=3,
        description="Seconds a focus event must persist without a blur before triggering a fetch",
        validation_alias=AliasChoices(
            "AGENTGRAPH_OBSERVATION_THRESHOLD_SECONDS",
            "AGENTGRAPH_DWELL_THRESHOLD_SECONDS",
        ),
    )
    observation_poll_interval_seconds: float = Field(
        default=1.0,
        description="How often the observation evaluator scans for mature focus events",
        validation_alias=AliasChoices(
            "AGENTGRAPH_OBSERVATION_POLL_INTERVAL_SECONDS",
            "AGENTGRAPH_DWELL_POLL_INTERVAL_SECONDS",
        ),
    )
    poll_interval_seconds: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Global background connector poll interval in seconds. If unset, each "
            "connector uses its own interval; 0 disables scheduled polling."
        ),
    )

    # Knowledge graph
    retention_days: int = Field(
        default=90,
        description=(
            "Retention window for observable entities, based on observed_at or local "
            "created_at when never observed"
        ),
    )
    embedding_model: str = Field(
        default="BAAI/bge-small-en-v1.5",
        description="FastEmbed model name for content embeddings",
    )
    embedding_dimensions: int = Field(default=384)

    # Connectors
    slack_workspace_id: str | None = Field(
        default=None,
        description="Slack workspace ID (e.g. T01ABC123) to observe; others are ignored",
    )
    # Logging
    log_level: str = Field(default="INFO")
    log_file: Path = Field(default=Path("/tmp/agentgraph.log"))

    def __init__(self, **values: Any) -> None:
        # Resolve the config-directory .env at instantiation time as well as
        # at module import time, since callers may set the environment first.
        values.setdefault("_env_file", [str(get_config_paths()[0] / ".env"), ".env"])
        super().__init__(**values)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
