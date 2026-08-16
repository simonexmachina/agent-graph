"""Google OAuth2 flow for all Google connectors (Docs, Sheets, Drive, Gmail)."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import argparse
import socket
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import NoReturn
from urllib.parse import parse_qs, urlparse

import typer

from agentgraph.auth.credentials import (
    load_platform_accounts,
    save_platform,
    upsert_platform_account,
)
from agentgraph_connector_google.provider import (
    GOOGLE_OAUTH_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET,
    GOOGLE_SCOPES,
    GOOGLE_TOKEN_URI,
    GoogleCredentials,
    verify_google_auth,
)


class _AuthArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


def _validate_args(args: list[str]) -> None:
    parser = _AuthArgumentParser(add_help=False, prog="agentgraph auth google")
    parser.parse_args(args)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def run_oauth_flow(
    account_id: str | None = None,
    add: bool = False,
    args: list[str] | None = None,
) -> None:
    """Interactive OAuth2 browser flow. Stores credentials on completion."""
    _validate_args(args or [])

    existing_accounts = load_platform_accounts("google")
    existing_data = None
    if account_id is not None:
        existing_data = next(
            (item for item in existing_accounts if item.get("account_id") == account_id), None
        )
    elif existing_accounts and not add:
        existing_data = existing_accounts[0]
    existing = GoogleCredentials(**existing_data) if existing_data else None

    if existing:
        # Probe the saved refresh token before forcing the user back through
        # the browser. If it still works, offer to skip.
        raw_account_id = existing_data.get("account_id") if existing_data else None
        verify_account_id = str(raw_account_id) if raw_account_id is not None else None
        status, detail = (
            verify_google_auth(verify_account_id)
            if verify_account_id is not None
            else verify_google_auth()
        )
        if status == "ok":
            typer.echo(f"\nGoogle is already authenticated as {detail}.")
            if not typer.confirm(
                "Re-authenticate anyway (e.g. to switch accounts or grant new scopes)?",
                default=False,
            ):
                typer.echo("Keeping existing credentials.")
                return
        else:
            typer.echo(f"\nGoogle credentials need re-authentication: {detail or status}.")
            typer.echo("Re-opening browser consent using AgentGraph's packaged OAuth client.")

        typer.echo(
            f"Re-authenticating as {existing.user_email or 'existing account'} with updated scopes."
        )

    client_id = GOOGLE_OAUTH_CLIENT_ID

    port = _find_free_port()
    redirect_uri = f"http://localhost:{port}"

    from google_auth_oauthlib.flow import Flow  # type: ignore[import-untyped]

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
            "redirect_uris": [redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": GOOGLE_TOKEN_URI,
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
        access_token=token.token or "",
        refresh_token=token.refresh_token or "",
        token_expiry=token.expiry,
        user_email=user_email,
        display_name=display_name,
    )
    resolved_account_id = account_id or (
        user_email.lower() if user_email else f"google:{len(existing_accounts) + 1}"
    )
    if not add and len(existing_accounts) <= 1 and account_id is None:
        save_platform(
            "google", {**creds.model_dump(mode="json"), "account_id": resolved_account_id}
        )
    else:
        upsert_platform_account("google", resolved_account_id, creds, make_default=True)
    from agentgraph.config import get_config_paths

    _, _, _, credentials_file, _ = get_config_paths()
    msg = f"Google credentials saved to {credentials_file}"
    if user_email:
        msg += f" (authenticated as {user_email})"
    typer.echo(msg)
    command = f"agentgraph connector gmail ingest --account {resolved_account_id}"
    start_backfill = sys.stdin.isatty() and typer.confirm(
        "Start Gmail historical backfill for this account now?", default=False
    )
    if start_backfill:
        try:
            from agentgraph.cli_sync import queue_connector_ingest

            queue_connector_ingest("gmail", account_id=resolved_account_id)
            typer.echo("Gmail backfill queued - progress in server logs (agentgraph serve)")
        except Exception as exc:
            typer.echo(f"Could not queue Gmail backfill: {exc}", err=True)
            typer.echo(f"Run later: {command}")
    else:
        typer.echo(f"Run later to import Gmail history: {command}")


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
