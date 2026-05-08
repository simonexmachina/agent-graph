"""Tests for credential storage."""

from __future__ import annotations

import pytest
from pathlib import Path

from agentgraph.auth.credentials import GoogleCredentials, load_platform, save_platform
from agentgraph_connector_slack.auth import SlackCredentials, load_slack_creds
from agentgraph_connector_discord.auth import DiscordCredentials, load_discord_creds


@pytest.fixture
def tmp_creds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    creds_file = tmp_path / "credentials.json"
    monkeypatch.setattr("agentgraph.auth.credentials.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("agentgraph.auth.credentials.CREDENTIALS_FILE", creds_file)
    return creds_file


def test_load_returns_none_when_no_file(tmp_creds: Path) -> None:
    assert load_platform("google") is None
    assert load_platform("slack") is None


def test_save_and_load_roundtrip(tmp_creds: Path) -> None:
    save_platform("slack", {"xoxc_token": "xoxc-test", "d_cookie": "abc123", "user_id": None})
    data = load_platform("slack")
    assert data is not None
    assert data["xoxc_token"] == "xoxc-test"
    assert data["d_cookie"] == "abc123"
    assert load_platform("google") is None


def test_save_sets_restricted_permissions(tmp_creds: Path) -> None:
    save_platform("test", {"key": "value"})
    mode = oct(tmp_creds.stat().st_mode)[-3:]
    assert mode == "600"


def test_save_merges_platforms(tmp_creds: Path) -> None:
    save_platform("slack", {"xoxc_token": "tok"})
    save_platform("discord", {"bot_token": "bot"})
    assert load_platform("slack") == {"xoxc_token": "tok"}
    assert load_platform("discord") == {"bot_token": "bot"}


def test_google_credentials_model() -> None:
    g = GoogleCredentials(
        client_id="id",
        client_secret="secret",
        access_token="tok",
        refresh_token="ref",
    )
    assert g.token_uri == "https://oauth2.googleapis.com/token"


def test_save_model_instance(tmp_creds: Path) -> None:
    g = GoogleCredentials(
        client_id="id",
        client_secret="secret",
        access_token="tok",
        refresh_token="ref",
        user_email="user@example.com",
    )
    save_platform("google", g)
    data = load_platform("google")
    assert data is not None
    assert data["client_id"] == "id"
    assert data["user_email"] == "user@example.com"


# ---------------------------------------------------------------------------
# Connector credential loaders
# ---------------------------------------------------------------------------

def test_load_slack_creds_raises_when_missing(tmp_creds: Path) -> None:
    with pytest.raises(RuntimeError, match="agentgraph auth slack"):
        load_slack_creds()


def test_load_slack_creds_returns_model(tmp_creds: Path) -> None:
    save_platform("slack", {"xoxc_token": "xoxc-T123-rest", "d_cookie": "abc", "user_id": "U999"})
    creds = load_slack_creds()
    assert isinstance(creds, SlackCredentials)
    assert creds.xoxc_token == "xoxc-T123-rest"
    assert creds.d_cookie == "abc"
    assert creds.user_id == "U999"


def test_load_discord_creds_raises_when_missing(tmp_creds: Path) -> None:
    with pytest.raises(RuntimeError, match="agentgraph auth discord"):
        load_discord_creds()


def test_load_discord_creds_returns_model(tmp_creds: Path) -> None:
    save_platform("discord", {"bot_token": "Bot.tok.en", "bot_user_id": "B123"})
    creds = load_discord_creds()
    assert isinstance(creds, DiscordCredentials)
    assert creds.bot_token == "Bot.tok.en"
    assert creds.bot_user_id == "B123"
