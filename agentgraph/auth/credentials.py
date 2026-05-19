"""Credential storage in the AgentGraph config directory.

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


class PlatformAccounts(BaseModel):
    accounts: list[dict[str, Any]]
    default_account_id: str | None = None


def _load_all_credentials() -> dict[str, Any]:
    if not CREDENTIALS_FILE.exists():
        return {}
    try:
        data = json.loads(CREDENTIALS_FILE.read_text())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_all_credentials(raw: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text(json.dumps(raw, indent=2, default=str))
    CREDENTIALS_FILE.chmod(0o600)


def load_platform(platform: str) -> dict[str, Any] | None:
    """Return the stored credential dict for a platform, or None if absent."""
    accounts = load_platform_accounts(platform)
    if not accounts:
        return None
    return accounts[0]


def load_platform_account(platform: str, account_id: str | None = None) -> dict[str, Any] | None:
    """Return the stored credential dict for one account, or the default account if omitted."""
    val = _load_all_credentials().get(platform)
    if not isinstance(val, dict):
        return None
    if "accounts" not in val:
        return val

    try:
        data = PlatformAccounts(**val)
    except Exception:
        return None
    if not data.accounts:
        return None
    target_id = account_id or data.default_account_id
    if target_id:
        for account in data.accounts:
            if account.get("account_id") == target_id:
                return account
    return data.accounts[0]


def load_platform_accounts(platform: str) -> list[dict[str, Any]]:
    """Return every stored account credential dict for a platform."""
    val = _load_all_credentials().get(platform)
    if not isinstance(val, dict):
        return []
    if "accounts" not in val:
        return [val]
    try:
        data = PlatformAccounts(**val)
    except Exception:
        return []
    return data.accounts


def save_platform(platform: str, data: Any) -> None:
    """Persist credentials for a platform, merging with the existing file."""
    raw = _load_all_credentials()
    raw[platform] = data.model_dump(mode="json") if hasattr(data, "model_dump") else data
    _write_all_credentials(raw)


def save_platform_accounts(
    platform: str,
    accounts: list[Any],
    *,
    default_account_id: str | None = None,
) -> None:
    """Persist all accounts for a platform."""
    serialised = [
        account.model_dump(mode="json") if hasattr(account, "model_dump") else account
        for account in accounts
    ]
    raw = _load_all_credentials()
    raw[platform] = PlatformAccounts(
        accounts=serialised,
        default_account_id=default_account_id,
    ).model_dump(mode="json")
    _write_all_credentials(raw)


def upsert_platform_account(
    platform: str,
    account_id: str,
    data: Any,
    *,
    make_default: bool = False,
) -> None:
    """Insert or update one account for a platform."""
    existing = load_platform_accounts(platform)
    payload = data.model_dump(mode="json") if hasattr(data, "model_dump") else dict(data)
    payload["account_id"] = account_id

    updated = False
    for i, account in enumerate(existing):
        if account.get("account_id") == account_id:
            existing[i] = payload
            updated = True
            break
    if not updated:
        existing.append(payload)

    default_id = account_id if make_default else None
    if default_id is None:
        current = _load_all_credentials().get(platform)
        if isinstance(current, dict) and "default_account_id" in current:
            default_id = current.get("default_account_id")
    save_platform_accounts(platform, existing, default_account_id=default_id or account_id)
