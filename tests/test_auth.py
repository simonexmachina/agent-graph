"""Tests for credential storage."""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from agentgraph.auth.credentials import (
    Credentials,
    GoogleCredentials,
    SlackCredentials,
    load,
    save,
)


@pytest.fixture
def tmp_creds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    creds_file = tmp_path / "credentials.json"
    monkeypatch.setattr("agentgraph.auth.credentials.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("agentgraph.auth.credentials.CREDENTIALS_FILE", creds_file)
    return creds_file


def test_load_returns_empty_when_no_file(tmp_creds: Path) -> None:
    creds = load()
    assert creds.google is None
    assert creds.slack is None


def test_save_and_load_roundtrip(tmp_creds: Path) -> None:
    creds = Credentials(
        slack=SlackCredentials(xoxc_token="xoxc-test", d_cookie="abc123")
    )
    save(creds)
    loaded = load()
    assert loaded.slack is not None
    assert loaded.slack.xoxc_token == "xoxc-test"
    assert loaded.slack.d_cookie == "abc123"
    assert loaded.google is None


def test_save_sets_restricted_permissions(tmp_creds: Path) -> None:
    save(Credentials())
    mode = oct(tmp_creds.stat().st_mode)[-3:]
    assert mode == "600"


def test_google_credentials_model() -> None:
    g = GoogleCredentials(
        client_id="id",
        client_secret="secret",
        access_token="tok",
        refresh_token="ref",
    )
    assert g.token_uri == "https://oauth2.googleapis.com/token"
