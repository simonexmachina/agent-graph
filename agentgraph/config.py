"""Application configuration loaded from environment variables and ~/.agentgraph/config.toml."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = Path.home() / ".agentgraph"
CONFIG_FILE = CONFIG_DIR / "config.toml"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTGRAPH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = Field(
        default="postgresql://agentgraph:agentgraph@localhost:5432/agentgraph",
        description="PostgreSQL connection URL",
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
        default="all-MiniLM-L6-v2",
        description="sentence-transformers model name for content embeddings",
    )
    embedding_dimensions: int = Field(default=384)

    # Connectors
    slack_workspace_id: str | None = Field(
        default=None,
        description="Slack workspace ID (e.g. T01ABC123) to observe; others are ignored",
    )
    google_auth_provider: str = Field(
        default="oauth",
        description="Google auth provider: 'oauth' (custom OAuth2 flow) or 'gcloud' (Application Default Credentials)",
    )

    # Logging
    log_level: str = Field(default="INFO")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
