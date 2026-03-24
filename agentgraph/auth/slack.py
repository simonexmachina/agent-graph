"""Slack cookie credential flow."""

from __future__ import annotations

import typer

from agentgraph.auth.credentials import SlackCredentials, update


def run_cookie_flow() -> None:
    """Guide user through extracting Slack cookie credentials from DevTools."""
    typer.echo(
        "\n"
        "To get your Slack credentials:\n"
        "\n"
        "  1. Open Slack in your browser (app.slack.com)\n"
        "  2. Open DevTools  →  Application  →  Cookies  →  https://app.slack.com\n"
        "  3. Find the cookie named  d  — copy its value\n"
        "  4. Find the token in Local Storage  →  localConfig_v2\n"
        "     (look for a key starting with xoxc-)\n"
        "\n"
        "  Alternatively: in DevTools  →  Network, make any Slack request,\n"
        "  inspect the Authorization header for the xoxc- token and the\n"
        "  Cookie header for the d= value.\n"
    )

    xoxc_token = typer.prompt("xoxc- token").strip()
    if not xoxc_token.startswith("xoxc-"):
        typer.echo("Warning: token doesn't start with 'xoxc-' — double-check the value.")

    d_cookie = typer.prompt("d cookie value").strip()

    creds = SlackCredentials(xoxc_token=xoxc_token, d_cookie=d_cookie)
    update("slack", creds)
    typer.echo("\nSlack credentials saved to ~/.agentgraph/credentials.json")
