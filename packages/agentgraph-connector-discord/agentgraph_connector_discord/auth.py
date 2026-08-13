"""Discord bot token credential flow."""

from __future__ import annotations

import os

from pydantic import BaseModel


class DiscordCredentials(BaseModel):
    bot_token: str
    bot_user_id: str | None = None


def load_discord_creds(account_id: str | None = None) -> DiscordCredentials:
    from agentgraph.auth.credentials import load_platform_account

    data = load_platform_account("discord", account_id)
    if data is None:
        raise RuntimeError("Discord credentials not configured. Run: agentgraph auth discord")
    return DiscordCredentials(**data)


def list_discord_accounts() -> list[dict[str, str | None]]:
    from agentgraph.auth.credentials import load_platform_accounts

    results: list[dict[str, str | None]] = []
    for raw in load_platform_accounts("discord"):
        try:
            creds = DiscordCredentials(**raw)
        except Exception:
            continue
        bot_user_id = creds.bot_user_id
        account_id = str(raw.get("account_id") or (f"discord:{bot_user_id}" if bot_user_id else "discord"))
        results.append({
            "account_id": account_id,
            "bot_user_id": bot_user_id,
            "label": bot_user_id or account_id,
        })
    return results


def _verify_token(token: str) -> tuple[str | None, str | None]:
    """Call Discord /users/@me. Return (bot_user_id, bot_username), or (None, None) on failure."""
    try:
        import httpx

        resp = httpx.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bot {token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            user_id: str | None = data.get("id")
            username: str | None = data.get("username")
            return user_id, username
    except Exception:
        pass
    return None, None


_FIRST_TIME_INSTRUCTIONS = """
To get your Discord bot token:

  1. Go to https://discord.com/developers/applications
  2. Click 'New Application', give it a name (e.g. AgentGraph)
  3. Go to 'Bot' in the left sidebar
  4. Click 'Reset Token' and copy the token shown
  5. Under 'Privileged Gateway Intents', enable:
       • Message Content Intent
  6. Go to 'OAuth2 → URL Generator':
       • Scopes: bot
       • Bot Permissions: Read Messages/View Channels, Read Message History
  7. Open the generated URL to invite the bot to your server
"""

_REAUTH_INSTRUCTIONS = """
To get a fresh bot token:

  1. Go to https://discord.com/developers/applications
  2. Click your existing application
  3. Go to 'Bot' in the left sidebar
  4. Click 'Reset Token' and copy the new token shown
"""


def _save_token(token: str) -> str | None:
    """Verify the token and save it. Return the bot username (or None if unverified)."""
    from agentgraph.auth.credentials import save_platform, upsert_platform_account

    bot_user_id, bot_username = _verify_token(token)
    creds = DiscordCredentials(bot_token=token, bot_user_id=bot_user_id)
    account_id = f"discord:{bot_user_id}" if bot_user_id else "discord"
    if not list_discord_accounts():
        save_platform("discord", {**creds.model_dump(mode="json"), "account_id": account_id})
    else:
        upsert_platform_account("discord", account_id, creds, make_default=True)
    return bot_username


def run_token_flow(account_id: str | None = None, add: bool = False) -> None:
    """Guide the user through obtaining (or refreshing) a Discord bot token."""
    import typer

    from agentgraph.auth.credentials import load_platform_account

    # 1. Non-interactive override via env var (useful for scripted re-auth)
    env_token = os.environ.get("AGENTGRAPH_DISCORD_BOT_TOKEN")
    if env_token:
        typer.echo("Using token from $AGENTGRAPH_DISCORD_BOT_TOKEN")
        username = _save_token(env_token.strip())
        suffix = f" (bot: {username})" if username else " (token unverified)"
        typer.echo(f"Discord credentials saved{suffix}")
        return

    # 2. Detect existing creds → re-auth path with terse instructions
    existing_raw = None if add else load_platform_account("discord", account_id)
    existing: DiscordCredentials | None = None
    if existing_raw is not None:
        try:
            existing = DiscordCredentials(**existing_raw)
        except Exception:
            existing = None

    if existing is not None:
        _, current_username = _verify_token(existing.bot_token)
        bot_label = current_username or existing.bot_user_id or "unknown"
        typer.echo(f"\nRe-authenticating Discord (current bot: {bot_label})")
        typer.echo(_REAUTH_INSTRUCTIONS)
        bot_token = typer.prompt(
            "Bot token (press Enter to keep current)",
            default="",
            show_default=False,
        ).strip()
        if not bot_token:
            typer.echo("Keeping existing token.")
            return
    else:
        typer.echo(_FIRST_TIME_INSTRUCTIONS)
        bot_token = typer.prompt("Bot token").strip()

    if not bot_token.startswith("MT") and not bot_token.startswith("OT") and "." not in bot_token:
        typer.echo("Warning: token format looks unexpected — double-check the value.")

    username = _save_token(bot_token)
    from agentgraph.config import get_config_paths

    _, _, _, credentials_file, _ = get_config_paths()
    msg = f"\nDiscord credentials saved to {credentials_file}"
    if username:
        msg += f" (bot: {username})"
    else:
        msg += " (token unverified — Discord API did not respond)"
    typer.echo(msg)
