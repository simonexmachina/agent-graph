"""Slack cookie credential flow."""

from __future__ import annotations

import argparse
from typing import NoReturn, cast

from pydantic import BaseModel


class _AuthArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


def cookie_options_from_args(args: list[str]) -> tuple[str | None, str | None]:
    parser = _AuthArgumentParser(add_help=False, prog="agentgraph auth slack")
    parser.add_argument("--xoxc-token")
    parser.add_argument("--d-cookie")
    parsed = parser.parse_args(args)
    return cast(str | None, parsed.xoxc_token), cast(str | None, parsed.d_cookie)


class SlackCredentials(BaseModel):
    xoxc_token: str
    d_cookie: str
    user_id: str | None = None
    team_id: str | None = None
    team_name: str | None = None


def load_slack_creds(account_id: str | None = None) -> SlackCredentials:
    from agentgraph.auth.credentials import load_platform_account

    data = load_platform_account("slack", account_id)
    if data is None:
        raise RuntimeError("Slack credentials not configured. Run: agentgraph auth slack")
    return SlackCredentials(**data)


def list_slack_accounts() -> list[dict[str, str | None]]:
    from agentgraph.auth.credentials import load_platform_accounts

    results: list[dict[str, str | None]] = []
    for raw in load_platform_accounts("slack"):
        try:
            creds = SlackCredentials(**raw)
        except Exception:
            continue
        team_id = creds.team_id
        user_id = creds.user_id
        account_id = str(raw.get("account_id") or (f"slack:{team_id}:{user_id}" if team_id and user_id else "slack"))
        label = creds.team_name or team_id or account_id
        results.append({
            "account_id": account_id,
            "team_id": team_id,
            "user_id": user_id,
            "label": label,
        })
    return results


def account_id_for_team(team_id: str) -> str | None:
    for account in list_slack_accounts():
        if account.get("team_id") == team_id:
            return str(account["account_id"])
    return None


def run_cookie_flow(
    account_id: str | None = None,
    add: bool = False,
    xoxc_token: str | None = None,
    d_cookie: str | None = None,
) -> None:
    """Guide the user through extracting Slack cookie credentials from DevTools.

    Pass xoxc_token and d_cookie to skip interactive prompts (e.g. from a browser-tool skill).
    """
    import typer

    from agentgraph.auth.credentials import save_platform, upsert_platform_account

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
    team_id: str | None = None
    team_name: str | None = None
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
            team_id = data.get("team_id")
            team_name = data.get("team")
    except Exception:
        pass

    creds = SlackCredentials(
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
        save_platform("slack", {**creds.model_dump(mode="json"), "account_id": resolved_account_id})
    else:
        upsert_platform_account("slack", resolved_account_id, creds, make_default=True)
    from agentgraph.config import CREDENTIALS_FILE

    msg = f"\nSlack credentials saved to {CREDENTIALS_FILE}"
    if user_id:
        label = f"{team_name} / {user_id}" if team_name else user_id
        msg += f" (authenticated as {label})"
    typer.echo(msg)
