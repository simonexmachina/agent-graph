"""Authentication method labels exposed by connector account status."""

from __future__ import annotations

from pathlib import Path

import pytest
from agentgraph_connector_discord import DiscordConnector
from agentgraph_connector_google.gdocs import GoogleDocsConnector

from agentgraph.auth.credentials import save_platform


@pytest.fixture
def credentials_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "credentials.json"
    monkeypatch.setattr("agentgraph.auth.credentials.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("agentgraph.auth.credentials.CREDENTIALS_FILE", path)
    return path


def test_discord_account_reports_bot_token_method(credentials_file: Path) -> None:
    _ = credentials_file
    save_platform("discord", {"bot_token": "test-token", "bot_user_id": "123"})

    accounts = DiscordConnector.list_accounts()

    assert len(accounts) == 1
    assert accounts[0].auth_method == "bot-token"


def test_google_account_reports_oauth_method(credentials_file: Path) -> None:
    _ = credentials_file
    save_platform(
        "google",
        {
            "client_id": "test-client",
            "access_token": "test-access-token",
            "refresh_token": "test-refresh-token",
            "user_email": "user@example.com",
        },
    )

    accounts = GoogleDocsConnector.list_accounts()

    assert len(accounts) == 1
    assert accounts[0].auth_method == "oauth"
