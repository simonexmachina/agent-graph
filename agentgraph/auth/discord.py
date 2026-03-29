"""Discord bot token credential flow."""

from __future__ import annotations

import typer

from agentgraph.auth.credentials import DiscordCredentials, update


def run_token_flow() -> None:
    """Guide user through creating a Discord bot and obtaining its token."""
    typer.echo(
        "\n"
        "To get your Discord bot token:\n"
        "\n"
        "  1. Go to https://discord.com/developers/applications\n"
        "  2. Click 'New Application', give it a name (e.g. AgentGraph)\n"
        "  3. Go to 'Bot' in the left sidebar\n"
        "  4. Click 'Reset Token' and copy the token shown\n"
        "  5. Under 'Privileged Gateway Intents', enable:\n"
        "       • Message Content Intent\n"
        "  6. Go to 'OAuth2 → URL Generator':\n"
        "       • Scopes: bot\n"
        "       • Bot Permissions: Read Messages/View Channels, Read Message History\n"
        "  7. Open the generated URL to invite the bot to your server\n"
    )

    bot_token = typer.prompt("Bot token").strip()
    if not bot_token.startswith("MT") and not bot_token.startswith("OT") and "." not in bot_token:
        typer.echo("Warning: token format looks unexpected — double-check the value.")

    # Verify token and fetch bot identity
    bot_user_id: str | None = None
    bot_username: str | None = None
    try:
        import httpx
        resp = httpx.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bot {bot_token}"},
            timeout=10,
        )
        data = resp.json()
        if resp.status_code == 200:
            bot_user_id = data.get("id")
            bot_username = data.get("username")
    except Exception:
        pass

    creds = DiscordCredentials(bot_token=bot_token, bot_user_id=bot_user_id)
    update("discord", creds)
    msg = "\nDiscord credentials saved to ~/.agentgraph/credentials.json"
    if bot_username:
        msg += f" (bot: {bot_username})"
    typer.echo(msg)
