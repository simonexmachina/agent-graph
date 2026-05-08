"""Credential storage at ~/.agentgraph/credentials.json.

Each platform stores its credentials under its own top-level key so
connectors remain fully independent. Use load_platform / save_platform.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from agentgraph.config import CONFIG_DIR, CREDENTIALS_FILE


class GoogleCredentials(BaseModel):
    """Google OAuth2 credentials stored under the 'google' platform key."""

    client_id: str
    client_secret: str
    access_token: str
    refresh_token: str
    token_uri: str = "https://oauth2.googleapis.com/token"
    token_expiry: datetime | None = None
    user_email: str | None = None
    display_name: str | None = None


def load_platform(platform: str) -> dict[str, Any] | None:
    """Return the stored credential dict for a platform, or None if absent."""
    if not CREDENTIALS_FILE.exists():
        return None
    try:
        data = json.loads(CREDENTIALS_FILE.read_text())
    except Exception:
        return None
    val = data.get(platform)
    return val if isinstance(val, dict) else None


def save_platform(platform: str, data: Any) -> None:
    """Persist credentials for a platform, merging with the existing file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    raw: dict[str, Any] = {}
    if CREDENTIALS_FILE.exists():
        try:
            raw = json.loads(CREDENTIALS_FILE.read_text())
        except Exception:
            pass
    raw[platform] = data.model_dump(mode="json") if hasattr(data, "model_dump") else data
    CREDENTIALS_FILE.write_text(json.dumps(raw, indent=2, default=str))
    CREDENTIALS_FILE.chmod(0o600)
