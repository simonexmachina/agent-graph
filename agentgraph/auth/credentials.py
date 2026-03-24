"""Credential storage and retrieval from ~/.agentgraph/credentials.json."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agentgraph.config import CONFIG_DIR, CREDENTIALS_FILE


class GoogleCredentials(BaseModel):
    client_id: str
    client_secret: str
    access_token: str
    refresh_token: str
    token_uri: str = "https://oauth2.googleapis.com/token"


class SlackCredentials(BaseModel):
    xoxc_token: str
    d_cookie: str


class Credentials(BaseModel):
    google: GoogleCredentials | None = None
    slack: SlackCredentials | None = None


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
