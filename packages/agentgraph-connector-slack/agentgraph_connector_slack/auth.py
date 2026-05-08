"""Slack cookie credential flow."""

from __future__ import annotations

from pydantic import BaseModel


class SlackCredentials(BaseModel):
    xoxc_token: str
    d_cookie: str
    user_id: str | None = None


def load_slack_creds() -> SlackCredentials:
    from agentgraph.auth.credentials import load_platform

    data = load_platform("slack")
    if data is None:
        raise RuntimeError("Slack credentials not configured. Run: agentgraph auth slack")
    return SlackCredentials(**data)


def run_cookie_flow() -> None:
    """Guide the user through extracting Slack cookie credentials from DevTools."""
    import typer

    from agentgraph.auth.credentials import save_platform

    typer.echo(
        "\n"
        "To get your Slack credentials:\n"
        "\n"
        "  1. Open Slack in your browser (app.slack.com)\n"
        "  2. Open DevTools  →  Network tab\n"
        "  3. Filter requests by 'api/' and click on any request to slack.com/api/\n"
        "  4. In the request:\n"
        "       • Payload tab  →  Form Data  →  token: xoxc-...\n"
        "         (this is your xoxc- token)\n"
        "       • Headers tab  →  Request Headers  →  Cookie: d=...\n"
        "         (copy just the value after 'd=')\n"
        "\n"
        "  Tip: send a message or switch channel to trigger a fresh API request.\n"
    )

    xoxc_token = typer.prompt("xoxc- token").strip()
    if not xoxc_token.startswith("xoxc-"):
        typer.echo("Warning: token doesn't start with 'xoxc-' — double-check the value.")

    d_cookie = typer.prompt("d cookie value").strip()

    user_id: str | None = None
    try:
        import httpx

        resp = httpx.get(
            "https://slack.com/api/auth.test",
            headers={
                "Authorization": f"Bearer {xoxc_token}",
                "Cookie": f"d={d_cookie}",
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            user_id = data.get("user_id")
    except Exception:
        pass

    creds = SlackCredentials(xoxc_token=xoxc_token, d_cookie=d_cookie, user_id=user_id)
    save_platform("slack", creds)
    msg = "\nSlack credentials saved to ~/.agentgraph/credentials.json"
    if user_id:
        msg += f" (authenticated as {user_id})"
    typer.echo(msg)
