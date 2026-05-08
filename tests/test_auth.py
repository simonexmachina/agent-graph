"""Tests for credential storage."""

from __future__ import annotations

import pytest
from pathlib import Path

from agentgraph.auth.credentials import GoogleCredentials, load_platform, save_platform


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
