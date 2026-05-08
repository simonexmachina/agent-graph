"""Microsoft OAuth2 flow for Microsoft Graph API access."""

from __future__ import annotations

import base64
import socket
import webbrowser
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import typer

from agentgraph.auth.credentials import MicrosoftCredentials, update

_AUTH_BASE = "https://login.microsoftonline.com/common/oauth2/v2.0"
_SCOPES = "Files.Read.All Sites.Read.All User.Read offline_access"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def run_oauth_flow() -> None:
    """Interactive OAuth2 browser flow for Microsoft Graph. Stores credentials on completion."""
    from agentgraph.auth.credentials import load as load_creds

    stored = load_creds()
    existing = stored.microsoft

    if existing:
        typer.echo(f"Re-authenticating as {existing.user_email or 'existing account'}.")
        client_id = existing.client_id
        client_secret = existing.client_secret
    else:
        typer.echo(
            "\n"
            "To get your Microsoft OAuth credentials:\n"
            "\n"
            "  1. Go to https://portal.azure.com\n"
            "  2. Azure Active Directory → App registrations → New registration\n"
            "  3. Name: 'AgentGraph', Supported account types:\n"
            "     'Accounts in any organizational directory and personal Microsoft accounts'\n"
            "  4. Redirect URI: leave blank for now (we'll use http://localhost)\n"
            "  5. After creation, note the 'Application (client) ID'\n"
            "  6. Go to 'Certificates & secrets' → New client secret → copy the Value\n"
            "  7. Go to 'API permissions' → Add a permission → Microsoft Graph\n"
            "     → Delegated → add: Files.Read.All, Sites.Read.All, User.Read\n"
            "  8. Under 'Authentication' → Add a platform → Mobile and desktop\n"
            "     → add http://localhost as a redirect URI\n"
        )
        client_id = typer.prompt("Microsoft Application (client) ID")
        client_secret = typer.prompt("Microsoft client secret", hide_input=True)

    port = _find_free_port()
    redirect_uri = f"http://localhost:{port}"

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": _SCOPES,
        "response_mode": "query",
        "prompt": "consent",
    }
    auth_url = f"{_AUTH_BASE}/authorize?{urlencode(params)}"

    typer.echo("\nOpening browser for Microsoft authorization...")
    typer.echo(f"If the browser doesn't open, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    auth_code = _wait_for_callback(port)

    with httpx.Client() as client:
        resp = client.post(
            f"{_AUTH_BASE}/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": auth_code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        token_data = resp.json()

    access_token: str = token_data["access_token"]
    refresh_token: str = token_data["refresh_token"]
    expires_in: int = token_data.get("expires_in", 3600)
    token_expiry = _expiry_from_seconds(expires_in)

    user_email: str | None = None
    display_name: str | None = None
    try:
        with httpx.Client() as client:
            profile = client.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if profile.is_success:
                info = profile.json()
                user_email = info.get("mail") or info.get("userPrincipalName")
                display_name = info.get("displayName")
    except Exception:
        pass

    creds = MicrosoftCredentials(
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expiry=token_expiry,
        user_email=user_email,
        display_name=display_name,
    )
    update("microsoft", creds)
    msg = "Microsoft credentials saved to ~/.agentgraph/credentials.json"
    if user_email:
        msg += f" (authenticated as {user_email})"
    typer.echo(msg)


def get_access_token() -> str:
    """Return a valid Microsoft Graph access token, refreshing if needed."""
    from agentgraph.auth.credentials import load as load_creds, save

    creds = load_creds()
    if creds.microsoft is None:
        raise RuntimeError("No Microsoft credentials found. Run: agentgraph auth microsoft")

    m = creds.microsoft
    if m.token_expiry is None or _is_expired(m.token_expiry):
        m = _refresh_token(m)
        updated = creds.model_copy(update={"microsoft": m})
        save(updated)

    return m.access_token


def _refresh_token(m: MicrosoftCredentials) -> MicrosoftCredentials:
    with httpx.Client() as client:
        resp = client.post(
            f"{_AUTH_BASE}/token",
            data={
                "client_id": m.client_id,
                "client_secret": m.client_secret,
                "refresh_token": m.refresh_token,
                "grant_type": "refresh_token",
                "scope": _SCOPES,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    return m.model_copy(update={
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", m.refresh_token),
        "token_expiry": _expiry_from_seconds(data.get("expires_in", 3600)),
    })


def _is_expired(expiry: datetime | None) -> bool:
    if expiry is None:
        return True
    return datetime.now(UTC) >= expiry


def _expiry_from_seconds(seconds: int) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=seconds - 60)


def encode_sharing_url(url: str) -> str:
    """Encode a sharing URL in the format expected by the Microsoft Graph /shares endpoint."""
    encoded = base64.urlsafe_b64encode(url.encode()).rstrip(b"=").decode()
    return f"u!{encoded}"


def _wait_for_callback(port: int) -> str:
    """Spin up a one-shot HTTP server to capture the OAuth redirect code."""
    auth_code: list[str] = []

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            params = parse_qs(urlparse(self.path).query)
            code = params.get("code", [""])[0]
            auth_code.append(code)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Authorization complete. You can close this tab.</h2></body></html>"
            )

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = HTTPServer(("localhost", port), _Handler)
    server.handle_request()
    server.server_close()

    if not auth_code or not auth_code[0]:
        raise typer.Exit(code=1)
    return auth_code[0]
