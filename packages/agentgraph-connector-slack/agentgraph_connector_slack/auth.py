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


def run_cookie_flow(xoxc_token: str | None = None, d_cookie: str | None = None) -> None:
    """Guide the user through extracting Slack cookie credentials from DevTools.

    Pass xoxc_token and d_cookie to skip interactive prompts (e.g. from a browser-tool skill).
    """
    import typer

    from agentgraph.auth.credentials import save_platform

    if xoxc_token is None:
        typer.echo(
            "\n"
            "To get your Slack credentials:\n"
            "\n"
            "  Recommended: ask your agent to use the /slack-auth skill.\n"
            "  It can extract the xoxc token and d cookie from your browser session\n"
            "  and save them for AgentGraph.\n"
            "\n"
            "  Manual fallback:\n"
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
        xoxc_token_val: str = typer.prompt("xoxc- token").strip()
        if not xoxc_token_val.startswith("xoxc-"):
            typer.echo("Warning: token doesn't start with 'xoxc-' — double-check the value.")
    else:
        xoxc_token_val = xoxc_token
        if not xoxc_token_val.startswith("xoxc-"):
            typer.echo("Warning: token doesn't start with 'xoxc-' — double-check the value.")

    d_cookie_val: str = typer.prompt("d cookie value").strip() if d_cookie is None else d_cookie

    user_id: str | None = None
    try:
        import httpx

        resp = httpx.get(
            "https://slack.com/api/auth.test",
            headers={
                "Authorization": f"Bearer {xoxc_token_val}",
                "Cookie": f"d={d_cookie_val}",
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            user_id = data.get("user_id")
    except Exception:
        pass

    creds = SlackCredentials(xoxc_token=xoxc_token_val, d_cookie=d_cookie_val, user_id=user_id)
    save_platform("slack", creds)
    msg = "\nSlack credentials saved to ~/.agentgraph/credentials.json"
    if user_id:
        msg += f" (authenticated as {user_id})"
    typer.echo(msg)
