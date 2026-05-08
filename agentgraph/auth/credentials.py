"""Credential storage and retrieval from ~/.agentgraph/credentials.json."""

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from agentgraph.config import CONFIG_DIR, CREDENTIALS_FILE


class GoogleCredentials(BaseModel):
    client_id: str
    client_secret: str
    access_token: str
    refresh_token: str
    token_uri: str = "https://oauth2.googleapis.com/token"
    token_expiry: datetime | None = None
    user_email: str | None = None
    display_name: str | None = None


class SlackCredentials(BaseModel):
    xoxc_token: str
    d_cookie: str
    user_id: str | None = None


class DiscordCredentials(BaseModel):
    bot_token: str
    bot_user_id: str | None = None


class Credentials(BaseModel):
    google: GoogleCredentials | None = None
    slack: SlackCredentials | None = None
    discord: DiscordCredentials | None = None


def load() -> Credentials:
    if not CREDENTIALS_FILE.exists():
        return Credentials()
    with CREDENTIALS_FILE.open() as f:
        return Credentials.model_validate(json.load(f))


def save(creds: Credentials) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text(creds.model_dump_json(indent=2))
    CREDENTIALS_FILE.chmod(0o600)


def update(key: str, value: Any) -> None:
    creds = load()
    updated = creds.model_copy(update={key: value})
    save(updated)
