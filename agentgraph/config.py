"""Application configuration loaded from environment variables and the config directory."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_config_dir() -> Path:
    raw = os.environ.get("AGENTGRAPH_CONFIG_DIR")
    return Path(raw).expanduser() if raw else Path.home() / ".agentgraph"


CONFIG_DIR = _default_config_dir()
CONFIG_FILE = CONFIG_DIR / "config.toml"
CONFIG_YAML_FILE = CONFIG_DIR / "config.yaml"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
DEFAULT_SQLITE_PATH = str(CONFIG_DIR / "agentgraph.db")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTGRAPH_",
        # User-level config is loaded first;
        # project-local .env takes precedence.
        env_file=[str(CONFIG_DIR / ".env"), ".env"],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Backend selection
    backend: str = Field(
        default="sqlite",
        description="Persistence backend: 'sqlite' | any installed plugin",
    )
    backend_sqlite_path: str = Field(
        default=DEFAULT_SQLITE_PATH,
        description="Path to SQLite database file (only used when backend='sqlite')",
    )
    backend_sqlite_vector_mode: str = Field(
        default="sqlite-vec",
        description="SQLite vector search mode: 'sqlite-vec' | 'numpy' | 'bm25-only'",
    )

    # Server
    server_host: str = Field(default="127.0.0.1")
    server_port: int = Field(default=8765)

    # Dwell detection
    dwell_threshold_seconds: int = Field(
        default=3,
        description="Seconds a focus event must persist without a blur before triggering a fetch",
    )
    dwell_poll_interval_seconds: float = Field(
        default=1.0,
        description="How often the dwell evaluator scans for mature focus events",
    )

    # Knowledge graph
    retention_days: int = Field(
        default=90,
        description="Days since last_accessed before an entity is garbage collected",
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


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
