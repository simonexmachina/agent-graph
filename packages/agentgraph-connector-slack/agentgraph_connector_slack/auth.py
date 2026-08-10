"""Slack OAuth and browser-session credentials."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import secrets
import time
import webbrowser
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from urllib.parse import parse_qs, urlencode, urlparse
from weakref import WeakKeyDictionary

import httpx
from pydantic import BaseModel, Field, TypeAdapter

SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.user.access"
SLACK_AUTHORIZE_URL = "https://slack.com/oauth/v2_user/authorize"
DEFAULT_REDIRECT_URI = "http://localhost:8766/slack/oauth/callback"
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

_refresh_locks: WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[str, asyncio.Lock]
] = WeakKeyDictionary()


class SlackOAuthCallback(BaseModel):
    code: str | None = None
    state: str | None = None
    error: str | None = None


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


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _wait_for_oauth_callback(
    redirect_uri: str,
    *,
    timeout_seconds: float = 300,
) -> SlackOAuthCallback:
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("Slack OAuth redirect must use http://localhost or http://127.0.0.1")
    if parsed.port is None:
        raise ValueError("Slack OAuth redirect must include a local port")

    result: SlackOAuthCallback | None = None
    expected_path = parsed.path or "/"

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            nonlocal result
            request_url = urlparse(self.path)
            if request_url.path != expected_path:
                self.send_error(404)
                return
            query = parse_qs(request_url.query)
            result = SlackOAuthCallback(
                code=query.get("code", [None])[0],
                state=query.get("state", [None])[0],
                error=query.get("error", [None])[0],
            )
            body = b"Slack authorization received. You can close this window."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            _ = (format, args)

    deadline = time.monotonic() + timeout_seconds
    with HTTPServer((parsed.hostname, parsed.port), CallbackHandler) as server:
        while result is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    "Timed out waiting five minutes for Slack authorization. "
                    "If you requested app approval, rerun this command after Slackbot "
                    "confirms approval."
                )
            server.timeout = remaining
            server.handle_request()
    return result


def _exchange_oauth_code(
    *,
    code: str,
    verifier: str,
    client_id: str,
    redirect_uri: str,
) -> dict[str, Any]:
    response = httpx.post(
        SLACK_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack OAuth exchange failed: {data.get('error', 'unknown')}")
    return data


def _manifest_text() -> str:
    manifest_path = Path(__file__).with_name("slack-app-manifest.yaml")
    return manifest_path.read_text().rstrip()


def _manifest_block() -> str:
    return f"AgentGraph Slack app manifest:\n\n{_manifest_text()}\n"


def _admin_setup_instructions() -> str:
    return (
        "\nCreate the AgentGraph Slack app:\n\n"
        "  1. Open https://api.slack.com/apps\n"
        "  2. Choose Create New App > From an app manifest.\n"
        "  3. Select the workspace you want AgentGraph to connect to.\n"
        "  4. Paste the manifest printed below.\n"
        "  5. Create and approve the app. Email access is optional.\n"
        "  6. Open Basic Information > App Credentials and copy the Client ID.\n\n"
        f"{_manifest_block()}"
    )


def _member_creation_instructions() -> str:
    return (
        "\nCheck whether you can create the AgentGraph app:\n\n"
        "  1. Open https://api.slack.com/apps\n"
        "  2. Choose Create New App > From an app manifest.\n"
        "  3. At Pick a workspace, look for the workspace you want AgentGraph "
        "to connect to.\n"
    )


def _member_visible_workspace_instructions() -> str:
    return (
        "\nCreate the AgentGraph Slack app:\n\n"
        "  1. Select that workspace and continue.\n"
        "  2. Paste the manifest printed below.\n"
        "  3. Review the configuration and choose Create.\n"
        "  4. Open Basic Information > App Credentials and copy the Client ID.\n\n"
        f"{_manifest_block()}"
    )


def _member_missing_workspace_instructions() -> str:
    return (
        "\nThe workspace is not available in Slack's app creation list.\n\n"
        "Ask a Workspace Owner or app manager either to give you permission to\n"
        "create internal apps, or to create and approve AgentGraph using the\n"
        "manifest below.\n\n"
        "Example request:\n\n"
        "  Hi, I'd like to connect AgentGraph to Slack. AgentGraph indexes Slack\n"
        "  conversations that I can access into a local knowledge graph.\n\n"
        "  Could you either give me permission to create an internal Slack app,\n"
        "  or create and approve AgentGraph using the manifest below?\n\n"
        "  The required user scopes read public channels, private channels, DMs,\n"
        "  group DMs, and member profiles. Email access is optional. Once the app\n"
        "  is approved, please send me its Client ID. No client secret is needed.\n\n"
        f"{_manifest_block()}\n"
        "Slack cannot offer app approval until the app exists in the target\n"
        "workspace. When the admin sends the Client ID, rerun agentgraph auth\n"
        "slack, answer No to the admin-permission question, and choose option 1.\n"
    )


def _authorization_instructions() -> str:
    return (
        "\nSlack may show one of these actions:\n\n"
        "  Allow\n"
        "    Continue authorization now.\n\n"
        "  Request approval\n"
        "    Submit the request and wait for a Workspace Owner or app manager.\n"
        "    Rerun this command after Slackbot confirms approval, then enter the\n"
        "    same Client ID.\n\n"
        "  Installation blocked\n"
        "    Contact a Workspace Owner or app manager. Workspace policy does not\n"
        "    allow members to request this app.\n"
    )


def _available_oauth_client_id(account_id: str | None, *, add: bool) -> str | None:
    if not add:
        try:
            existing = load_slack_creds(account_id)
        except Exception:
            existing = None
        if isinstance(existing, SlackOAuthCredentials):
            return existing.client_id
    return os.environ.get("AGENTGRAPH_SLACK_CLIENT_ID", "").strip() or None


def _prompt_oauth_client_id() -> str:
    import typer

    while True:
        client_id = typer.prompt("Slack app Client ID").strip()
        if client_id:
            return client_id
        typer.echo("Slack app Client ID cannot be empty.")


def run_interactive_auth_flow(account_id: str | None = None, add: bool = False) -> None:
    """Prompt for a Slack authentication method and run the selected flow."""
    import click
    import typer

    typer.echo(
        "\nChoose how to connect Slack:\n"
        "  1. Slack user OAuth with PKCE [recommended]\n"
        "  2. Browser session credentials (xoxc token + d cookie) [fallback]\n"
    )
    choice = typer.prompt(
        "Authentication method",
        type=click.Choice(["1", "2"]),
        default="1",
        show_default=False,
    )
    if choice == "2":
        run_cookie_flow(account_id=account_id, add=add)
        return
    run_guided_oauth_flow(account_id=account_id, add=add)


def run_guided_oauth_flow(account_id: str | None = None, add: bool = False) -> None:
    """Resolve an existing client or guide the user through Slack app setup."""
    import click
    import typer

    client_id = _available_oauth_client_id(account_id, add=add)
    if client_id is not None:
        run_oauth_flow(account_id=account_id, add=add, client_id=client_id)
        return

    workspace_admin = typer.confirm(
        "Do you have admin permission in the Slack workspace you want to connect?",
        default=False,
    )
    if workspace_admin:
        typer.echo(_admin_setup_instructions())
        run_oauth_flow(
            account_id=account_id,
            add=add,
            client_id=_prompt_oauth_client_id(),
        )
        return

    typer.echo(
        "\nHow would you like to continue?\n\n"
        "  1. Enter a Client ID provided by a Slack admin\n"
        "  2. Set up or request the AgentGraph app\n"
    )
    choice = typer.prompt(
        "Choice",
        type=click.Choice(["1", "2"]),
        default="1",
        show_default=False,
    )
    if choice == "1":
        run_oauth_flow(
            account_id=account_id,
            add=add,
            client_id=_prompt_oauth_client_id(),
        )
        return

    typer.echo(_member_creation_instructions())
    workspace_visible = typer.confirm(
        "Can you see the workspace you want in Slack's Pick a workspace list?",
        default=False,
    )
    if not workspace_visible:
        typer.echo(_member_missing_workspace_instructions())
        return
    typer.echo(_member_visible_workspace_instructions())
    run_oauth_flow(
        account_id=account_id,
        add=add,
        client_id=_prompt_oauth_client_id(),
    )


def run_oauth_flow(
    account_id: str | None = None,
    add: bool = False,
    *,
    client_id: str | None = None,
) -> None:
    """Authorize a Slack user with PKCE and store rotating credentials."""
    import typer

    resolved_client_id = client_id or _available_oauth_client_id(account_id, add=add)
    if resolved_client_id is None:
        resolved_client_id = _prompt_oauth_client_id()
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(32)
    authorize_url = f"{SLACK_AUTHORIZE_URL}?{urlencode({
        'client_id': resolved_client_id,
        'scope': ','.join(sorted(REQUIRED_SCOPES | OPTIONAL_SCOPES)),
        'redirect_uri': DEFAULT_REDIRECT_URI,
        'state': state,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
    })}"
    typer.echo(_authorization_instructions())
    typer.echo(f"Opening Slack authorization in your browser:\n{authorize_url}")
    webbrowser.open(authorize_url)
    callback = _wait_for_oauth_callback(DEFAULT_REDIRECT_URI)
    if not callback.state or not secrets.compare_digest(callback.state, state):
        raise RuntimeError("Slack OAuth callback state did not match")
    if callback.error:
        raise RuntimeError(f"Slack OAuth authorization denied: {callback.error}")
    if not callback.code:
        raise RuntimeError("Slack OAuth callback did not include an authorization code")

    data = _exchange_oauth_code(
        code=callback.code,
        verifier=verifier,
        client_id=resolved_client_id,
        redirect_uri=DEFAULT_REDIRECT_URI,
    )
    access_token, refresh_token, expires_in, scopes = _oauth_values(data)
    missing_scopes = validate_required_scopes(scopes)
    if missing_scopes:
        raise RuntimeError(
            "Slack authorization is missing required scopes: " + ", ".join(missing_scopes)
        )
    team = data.get("team")
    team_data = cast(dict[str, Any], team) if isinstance(team, dict) else {}
    authed_user = data.get("authed_user")
    user_data = cast(dict[str, Any], authed_user) if isinstance(authed_user, dict) else {}
    team_id = team_data.get("id")
    user_id = user_data.get("id") or data.get("user_id")
    if not isinstance(team_id, str) or not isinstance(user_id, str):
        raise RuntimeError("Slack OAuth response did not identify the workspace and user")

    email: str | None = None
    if "users:read.email" in scopes:
        try:
            profile_response = httpx.get(
                "https://slack.com/api/users.info",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"user": user_id},
                timeout=10,
            )
            profile_data: dict[str, Any] = profile_response.json()
            raw_user = profile_data.get("user")
            user_profile = cast(dict[str, Any], raw_user) if isinstance(raw_user, dict) else {}
            raw_profile = user_profile.get("profile")
            profile = cast(dict[str, Any], raw_profile) if isinstance(raw_profile, dict) else {}
            raw_email = profile.get("email")
            email = raw_email if isinstance(raw_email, str) else None
        except Exception:
            email = None

    credentials = SlackOAuthCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        client_id=resolved_client_id,
        scopes=scopes,
        user_id=user_id,
        team_id=team_id,
        team_name=team_data.get("name") if isinstance(team_data.get("name"), str) else None,
        email=email,
    )
    resolved_account_id = account_id or f"slack:{team_id}:{user_id}"
    if account_id is not None and account_id != f"slack:{team_id}:{user_id}":
        raise RuntimeError(
            f"Slack identity {team_id}:{user_id} does not match requested account {account_id}"
        )
    from agentgraph.auth.credentials import upsert_platform_account

    upsert_platform_account("slack", resolved_account_id, credentials, make_default=True)
    from agentgraph.config import CREDENTIALS_FILE

    typer.echo(f"Slack OAuth credentials saved to {CREDENTIALS_FILE} ({resolved_account_id})")


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
    locks = _refresh_locks.setdefault(asyncio.get_running_loop(), {})
    lock = locks.setdefault(resolved_id, asyncio.Lock())
    async with lock:
        current = load_slack_creds(resolved_id)
        if not isinstance(current, SlackOAuthCredentials):
            raise RuntimeError("Slack OAuth credentials changed during refresh")
        now = datetime.now(UTC)
        expires_at = current.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if force and current.access_token != initial.access_token:
            return current
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
