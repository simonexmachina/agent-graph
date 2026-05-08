"""Google OAuth2 flow for all Google connectors (Docs, Sheets, Drive, Gmail)."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import socket
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import typer

from agentgraph.auth.credentials import GoogleCredentials, save_platform
from agentgraph.auth.google_provider import GOOGLE_SCOPES


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def run_oauth_flow() -> None:
    """Interactive OAuth2 browser flow. Stores credentials on completion."""
    from agentgraph.auth.credentials import load_platform

    existing_data = load_platform("google")
    existing = GoogleCredentials(**existing_data) if existing_data else None

    if existing:
        typer.echo(f"Re-authenticating as {existing.user_email or 'existing account'} with updated scopes.")
        client_id = existing.client_id
        client_secret = existing.client_secret
    else:
        typer.echo(
            "\n"
            "To get your Google OAuth credentials:\n"
            "\n"
            "  1. Go to https://console.cloud.google.com/\n"
            "  2. Create a project (or select an existing one)\n"
            "  3. Enable the APIs:\n"
            "       APIs & Services → Enable APIs → search for and enable:\n"
            "         • Google Docs API\n"
            "         • Google Sheets API\n"
            "         • Google Drive API\n"
            "         • Gmail API\n"
            "  4. Create OAuth credentials:\n"
            "       APIs & Services → Credentials → Create Credentials\n"
            "       → OAuth client ID → Application type: Desktop app\n"
            "  5. Copy the Client ID and Client Secret from the dialog\n"
            "  6. Under OAuth consent screen → Audience, add your email\n"
            "     as a Test user (required while the app is in testing mode)\n"
        )
        client_id = typer.prompt("Google OAuth client ID")
        client_secret = typer.prompt("Google OAuth client secret", hide_input=True)

    port = _find_free_port()
    redirect_uri = f"http://localhost:{port}"

    from google_auth_oauthlib.flow import Flow  # type: ignore[import-untyped]

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": [redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    flow: Flow = Flow.from_client_config(
        client_config,
        scopes=GOOGLE_SCOPES,
        redirect_uri=redirect_uri,
    )

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )

    typer.echo("\nOpening browser for Google authorization...")
    typer.echo(f"If the browser doesn't open, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    auth_code = _wait_for_callback(port)

    flow.fetch_token(code=auth_code)
    token = flow.credentials

    user_email: str | None = None
    display_name: str | None = None
    try:
        import requests  # type: ignore[import-untyped]

        resp = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {token.token}"},
            timeout=10,
        )
        if resp.ok:
            info = resp.json()
            user_email = info.get("email")
            display_name = info.get("name")
    except Exception:
        pass

    creds = GoogleCredentials(
        client_id=client_id,
        client_secret=client_secret,
        access_token=token.token or "",
        refresh_token=token.refresh_token or "",
        token_expiry=token.expiry,
        user_email=user_email,
        display_name=display_name,
    )
    save_platform("google", creds)
    msg = "Google credentials saved to ~/.agentgraph/credentials.json"
    if user_email:
        msg += f" (authenticated as {user_email})"
    typer.echo(msg)


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
