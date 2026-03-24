"""Google OAuth2 flow for Google Docs / Drive API access."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import typer
from google_auth_oauthlib.flow import Flow  # type: ignore[import-untyped]

from agentgraph.auth.credentials import GoogleCredentials, update

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
]

REDIRECT_URI = "http://localhost:8766"
CALLBACK_PORT = 8766


def run_oauth_flow() -> None:
    """Interactive OAuth2 browser flow. Stores credentials on completion."""
    client_id = typer.prompt("Google OAuth client ID")
    client_secret = typer.prompt("Google OAuth client secret", hide_input=True)

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": [REDIRECT_URI],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    flow: Flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )

    typer.echo("\nOpening browser for Google authorization...")
    typer.echo(f"If the browser doesn't open, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    auth_code = _wait_for_callback()

    flow.fetch_token(code=auth_code)
    token = flow.credentials

    creds = GoogleCredentials(
        client_id=client_id,
        client_secret=client_secret,
        access_token=token.token or "",
        refresh_token=token.refresh_token or "",
    )
    update("google", creds)
    typer.echo("Google credentials saved to ~/.agentgraph/credentials.json")


def _wait_for_callback() -> str:
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
            pass  # suppress request logs

    server = HTTPServer(("localhost", CALLBACK_PORT), _Handler)
    server.handle_request()
    server.server_close()

    if not auth_code or not auth_code[0]:
        raise typer.Exit(code=1)
    return auth_code[0]
