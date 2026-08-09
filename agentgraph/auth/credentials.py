"""Credential storage in the AgentGraph config directory.

Each platform stores its credentials under its own top-level key so
connectors remain fully independent. Use load_platform / save_platform.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from typing import Any, cast

from pydantic import BaseModel

from agentgraph.config import CONFIG_DIR, CREDENTIALS_FILE


class CredentialsFileError(ValueError):
    """The credentials file exists but could not be read as valid storage."""


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
    except Exception as exc:
        # Never fall back to "no credentials" here: callers would treat a
        # damaged file as a first-time setup and overwrite every platform.
        raise CredentialsFileError(
            f"Could not parse {CREDENTIALS_FILE}: {exc}. "
            "Fix or move the file aside, then re-run auth for each platform."
        ) from exc
    if not isinstance(data, dict):
        raise CredentialsFileError(
            f"Expected a JSON object at the top level of {CREDENTIALS_FILE}, got {type(data).__name__}."
        )
    return cast(dict[str, Any], data)


def _write_all_credentials(raw: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Write via a temp file in the same directory and rename, so a concurrent
    # writer can never leave a shorter document overlaid on a longer one.
    fd, tmp_name = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".credentials-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(raw, handle, indent=2, default=str)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, CREDENTIALS_FILE)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _validate_accounts(platform: str, val: dict[str, Any]) -> PlatformAccounts:
    try:
        return PlatformAccounts.model_validate(val)
    except Exception as exc:
        raise CredentialsFileError(
            f"Stored '{platform}' credentials in {CREDENTIALS_FILE} are malformed: {exc}. "
            f"Fix the file or re-run auth for {platform}."
        ) from exc


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
        return cast(dict[str, Any], val)

    data = _validate_accounts(platform, cast(dict[str, Any], val))
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
        return [cast(dict[str, Any], val)]
    return _validate_accounts(platform, cast(dict[str, Any], val)).accounts


def save_platform(platform: str, data: Any) -> None:
    """Persist credentials for a platform, merging with the existing file."""
    raw = _load_all_credentials()
    raw[platform] = data.model_dump(mode="json") if hasattr(data, "model_dump") else data
    _write_all_credentials(raw)


def remove_platform(platform: str) -> bool:
    """Remove all stored credentials for a platform.

    Returns true when credentials were present and removed.
    """
    raw = _load_all_credentials()
    if platform not in raw:
        return False
    del raw[platform]
    _write_all_credentials(raw)
    return True


def save_platform_accounts(
    platform: str,
    accounts: list[Any],
    *,
    default_account_id: str | None = None,
) -> None:
    """Persist all accounts for a platform."""
    serialised: list[dict[str, Any]] = [
        cast(dict[str, Any], account.model_dump(mode="json"))
        if hasattr(account, "model_dump")
        else cast(dict[str, Any], account)
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
            current_data = cast(dict[str, Any], current)
            raw_default_id = current_data.get("default_account_id")
            default_id = raw_default_id if isinstance(raw_default_id, str) else None
    save_platform_accounts(platform, existing, default_account_id=default_id or account_id)


def remove_platform_account(platform: str, account_id: str) -> bool:
    """Remove one stored account for a platform.

    Legacy single-account credentials are only removed when their stored
    account_id matches the requested account_id. Multi-account credentials
    drop the platform key entirely when the final account is removed.
    """
    raw = _load_all_credentials()
    val = raw.get(platform)
    if not isinstance(val, dict):
        return False
    data_val = cast(dict[str, Any], val)

    if "accounts" not in data_val:
        if data_val.get("account_id") != account_id:
            return False
        del raw[platform]
        _write_all_credentials(raw)
        return True

    try:
        data = PlatformAccounts.model_validate(data_val)
    except Exception:
        return False

    remaining = [account for account in data.accounts if account.get("account_id") != account_id]
    if len(remaining) == len(data.accounts):
        return False
    if not remaining:
        del raw[platform]
        _write_all_credentials(raw)
        return True

    default_account_id = data.default_account_id
    if default_account_id == account_id:
        raw_next_default = remaining[0].get("account_id")
        default_account_id = raw_next_default if isinstance(raw_next_default, str) else None
    raw[platform] = PlatformAccounts(
        accounts=remaining,
        default_account_id=default_account_id,
    ).model_dump(mode="json")
    _write_all_credentials(raw)
    return True
