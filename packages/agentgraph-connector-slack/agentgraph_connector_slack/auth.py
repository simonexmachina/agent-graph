"""Slack OAuth and browser-session credentials."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, cast

import httpx
from pydantic import BaseModel, Field, TypeAdapter

SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.user.access"
REQUIRED_SCOPES: frozenset[str] = frozenset({
    "channels:history",
    "channels:read",
    "groups:history",
    "groups:read",
    "im:history",
    "im:read",
    "mpim:history",
    "mpim:read",
    "users:read",
})
OPTIONAL_SCOPES: frozenset[str] = frozenset({"users:read.email"})
REFRESH_WINDOW = timedelta(minutes=5)


class SlackBrowserCredentials(BaseModel):
    auth_method: Literal["browser"] = "browser"
    xoxc_token: str
    d_cookie: str
    user_id: str | None = None
    team_id: str | None = None
    team_name: str | None = None


class SlackOAuthCredentials(BaseModel):
    auth_method: Literal["oauth"] = "oauth"
    access_token: str
    refresh_token: str
    expires_at: datetime
    client_id: str
    scopes: list[str]
    user_id: str
    team_id: str
    team_name: str | None = None
    email: str | None = None


SlackCredential = Annotated[
    SlackBrowserCredentials | SlackOAuthCredentials,
    Field(discriminator="auth_method"),
]
_CREDENTIAL_ADAPTER: TypeAdapter[SlackCredential] = TypeAdapter(SlackCredential)

# Backwards-compatible public name for callers that used the old model.
SlackCredentials = SlackBrowserCredentials

_refresh_locks: dict[str, asyncio.Lock] = {}


def parse_slack_credentials(raw: dict[str, Any]) -> SlackCredential:
    """Parse stored credentials, treating pre-discriminator records as browser auth."""
    data = dict(raw)
    data.setdefault("auth_method", "browser")
    return _CREDENTIAL_ADAPTER.validate_python(data)


def load_slack_creds(account_id: str | None = None) -> SlackCredential:
    from agentgraph.auth.credentials import load_platform_account

    data = load_platform_account("slack", account_id)
    if data is None:
        raise RuntimeError("Slack credentials not configured. Run: agentgraph auth slack")
    return parse_slack_credentials(data)


def list_slack_accounts() -> list[dict[str, str | None]]:
    from agentgraph.auth.credentials import load_platform_accounts

    results: list[dict[str, str | None]] = []
    for raw in load_platform_accounts("slack"):
        try:
            creds = parse_slack_credentials(raw)
        except Exception:
            continue
        team_id = creds.team_id
        user_id = creds.user_id
        account_id = str(
            raw.get("account_id")
            or (f"slack:{team_id}:{user_id}" if team_id and user_id else "slack")
        )
        label = creds.team_name or team_id or account_id
        results.append({
            "account_id": account_id,
            "team_id": team_id,
            "user_id": user_id,
            "label": label,
            "auth_method": creds.auth_method,
            "email": creds.email if isinstance(creds, SlackOAuthCredentials) else None,
        })
    return results


def account_id_for_team(team_id: str) -> str | None:
    for account in list_slack_accounts():
        if account.get("team_id") == team_id:
            return str(account["account_id"])
    return None


def validate_required_scopes(scopes: list[str] | str) -> list[str]:
    granted = set(scopes.split(",") if isinstance(scopes, str) else scopes)
    return sorted(REQUIRED_SCOPES - granted)


def _oauth_values(data: dict[str, Any]) -> tuple[str, str, int, list[str]]:
    authed_user = data.get("authed_user")
    user_data = cast(dict[str, Any], authed_user) if isinstance(authed_user, dict) else {}
    access_token = data.get("access_token") or user_data.get("access_token")
    refresh_token = data.get("refresh_token") or user_data.get("refresh_token")
    expires_in = data.get("expires_in") or user_data.get("expires_in")
    raw_scopes = data.get("scope") or user_data.get("scope") or ""
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        raise RuntimeError("Slack OAuth response did not include rotating user tokens")
    if not isinstance(expires_in, int | float):
        raise RuntimeError("Slack OAuth response did not include token expiry")
    scopes = [scope for scope in str(raw_scopes).split(",") if scope]
    return access_token, refresh_token, int(expires_in), scopes


async def refresh_oauth_credentials(
    account_id: str | None = None,
    *,
    force: bool = False,
    client: httpx.AsyncClient | None = None,
) -> SlackOAuthCredentials:
    """Refresh a rotating token once per account and persist the replacement atomically."""
    initial = load_slack_creds(account_id)
    if not isinstance(initial, SlackOAuthCredentials):
        raise RuntimeError("Slack browser credentials cannot be refreshed")
    resolved_id = account_id or f"slack:{initial.team_id}:{initial.user_id}"
    lock = _refresh_locks.setdefault(resolved_id, asyncio.Lock())
    async with lock:
        current = load_slack_creds(resolved_id)
        if not isinstance(current, SlackOAuthCredentials):
            raise RuntimeError("Slack OAuth credentials changed during refresh")
        now = datetime.now(UTC)
        expires_at = current.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if not force and expires_at > now + REFRESH_WINDOW:
            return current

        owns_client = client is None
        http = client or httpx.AsyncClient(timeout=30)
        try:
            response = await http.post(
                SLACK_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": current.refresh_token,
                    "client_id": current.client_id,
                },
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        finally:
            if owns_client:
                await http.aclose()
        if not data.get("ok"):
            raise RuntimeError(f"Slack OAuth refresh failed: {data.get('error', 'unknown')}")

        access_token, refresh_token, expires_in, returned_scopes = _oauth_values(data)
        refreshed = current.model_copy(update={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": now + timedelta(seconds=expires_in),
            "scopes": returned_scopes or current.scopes,
        })
        from agentgraph.auth.credentials import upsert_platform_account

        upsert_platform_account("slack", resolved_id, refreshed, make_default=False)
        return refreshed


async def slack_headers(
    account_id: str | None = None,
    *,
    force_refresh: bool = False,
    client: httpx.AsyncClient | None = None,
) -> dict[str, str]:
    creds = load_slack_creds(account_id)
    if isinstance(creds, SlackOAuthCredentials):
        expires_at = creds.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if force_refresh or expires_at <= datetime.now(UTC) + REFRESH_WINDOW:
            creds = await refresh_oauth_credentials(account_id, force=force_refresh, client=client)
        return {
            "Authorization": f"Bearer {creds.access_token}",
            "Content-Type": "application/json",
        }
    return {
        "Authorization": f"Bearer {creds.xoxc_token}",
        "Cookie": f"d={creds.d_cookie}",
        "Content-Type": "application/json",
    }


def run_cookie_flow(
    account_id: str | None = None,
    add: bool = False,
    xoxc_token: str | None = None,
    d_cookie: str | None = None,
) -> None:
    """Guide the user through extracting Slack browser-session credentials."""
    import typer

    from agentgraph.auth.credentials import save_platform, upsert_platform_account

    if xoxc_token is None:
        typer.echo(
            "\nBrowser-session fallback selected. Open Slack in a browser, inspect a "
            "slack.com/api request, and copy its xoxc token and d cookie.\n"
        )
        xoxc_token_val: str = typer.prompt("xoxc- token").strip()
    else:
        xoxc_token_val = xoxc_token
    if not xoxc_token_val.startswith("xoxc-"):
        typer.echo("Warning: token doesn't start with 'xoxc-' - double-check the value.")

    d_cookie_val: str = typer.prompt("d cookie value").strip() if d_cookie is None else d_cookie
    user_id: str | None = None
    team_id: str | None = None
    team_name: str | None = None
    try:
        response = httpx.get(
            "https://slack.com/api/auth.test",
            headers={
                "Authorization": f"Bearer {xoxc_token_val}",
                "Cookie": f"d={d_cookie_val}",
            },
            timeout=10,
        )
        data = response.json()
        if data.get("ok"):
            user_id = data.get("user_id")
            team_id = data.get("team_id")
            team_name = data.get("team")
    except Exception:
        pass

    creds = SlackBrowserCredentials(
        xoxc_token=xoxc_token_val,
        d_cookie=d_cookie_val,
        user_id=user_id,
        team_id=team_id,
        team_name=team_name,
    )
    resolved_account_id = account_id or (
        f"slack:{team_id}:{user_id}" if team_id and user_id else "slack"
    )
    if not add and account_id is None and not list_slack_accounts():
        save_platform(
            "slack", {**creds.model_dump(mode="json"), "account_id": resolved_account_id}
        )
    else:
        upsert_platform_account("slack", resolved_account_id, creds, make_default=True)
    from agentgraph.config import CREDENTIALS_FILE

    msg = f"\nSlack credentials saved to {CREDENTIALS_FILE}"
    if user_id:
        label = f"{team_name} / {user_id}" if team_name else user_id
        msg += f" (authenticated as {label})"
    typer.echo(msg)
