"""Tests for credential storage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from agentgraph_connector_discord.auth import DiscordCredentials, load_discord_creds
from agentgraph_connector_slack.auth import SlackCredentials, load_slack_creds

from agentgraph.auth.credentials import (
    CredentialsFileError,
    GoogleCredentials,
    load_platform,
    load_platform_account,
    load_platform_accounts,
    remove_platform,
    remove_platform_account,
    save_platform,
    upsert_platform_account,
)
from agentgraph.auth.google_provider import verify_google_auth


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


def test_remove_platform_deletes_only_requested_platform(tmp_creds: Path) -> None:
    save_platform("slack", {"xoxc_token": "tok"})
    save_platform("discord", {"bot_token": "bot"})

    assert remove_platform("slack") is True
    assert load_platform("slack") is None
    assert load_platform("discord") == {"bot_token": "bot"}
    assert remove_platform("slack") is False


def test_corrupt_file_raises_instead_of_reporting_no_credentials(tmp_creds: Path) -> None:
    # A truncated/overlaid write must not look like a first-time setup, or the
    # auth flow re-prompts for an OAuth client and clobbers other platforms.
    save_platform("google", {"client_id": "id", "client_secret": "secret"})
    tmp_creds.write_text(tmp_creds.read_text() + '  "discord": {')

    with pytest.raises(CredentialsFileError, match="Could not parse"):
        load_platform("google")
    with pytest.raises(CredentialsFileError):
        load_platform_accounts("google")
    with pytest.raises(CredentialsFileError):
        load_platform_account("google")


def test_corrupt_file_is_not_overwritten_by_save(tmp_creds: Path) -> None:
    save_platform("slack", {"xoxc_token": "tok"})
    corrupt = tmp_creds.read_text() + "}}"
    tmp_creds.write_text(corrupt)

    with pytest.raises(CredentialsFileError):
        save_platform("google", {"client_id": "id"})
    assert tmp_creds.read_text() == corrupt


def test_malformed_accounts_block_raises(tmp_creds: Path) -> None:
    tmp_creds.write_text('{"google": {"accounts": "not-a-list"}}')

    with pytest.raises(CredentialsFileError, match="malformed"):
        load_platform_accounts("google")


def test_non_object_top_level_raises(tmp_creds: Path) -> None:
    tmp_creds.write_text("[]")

    with pytest.raises(CredentialsFileError, match="top level"):
        load_platform("google")


def test_write_is_atomic_and_leaves_no_temp_files(tmp_creds: Path) -> None:
    save_platform("slack", {"xoxc_token": "tok"})
    save_platform("google", {"client_id": "id"})

    siblings = sorted(p.name for p in tmp_creds.parent.iterdir())
    assert siblings == ["credentials.json"]
    assert oct(tmp_creds.stat().st_mode)[-3:] == "600"


def test_shorter_write_truncates_previous_content(tmp_creds: Path) -> None:
    # The corruption this guards against: a short document left overlaid on a
    # longer one, leaving trailing bytes after the closing brace.
    save_platform("google", {"client_id": "x" * 500})
    save_platform("google", {"client_id": "y"})
    remove_platform("google")
    save_platform("slack", {"xoxc_token": "tok"})

    assert tmp_creds.read_text().rstrip().endswith("}")
    assert load_platform("slack") == {"xoxc_token": "tok"}
    assert load_platform("google") is None


def test_upsert_platform_account_preserves_multiple_accounts(tmp_creds: Path) -> None:
    upsert_platform_account(
        "google", "user-one@example.com", {"user_email": "user-one@example.com"}
    )
    upsert_platform_account(
        "google", "user-two@example.com", {"user_email": "user-two@example.com"}
    )

    accounts = load_platform_accounts("google")

    assert [account["account_id"] for account in accounts] == [
        "user-one@example.com",
        "user-two@example.com",
    ]
    assert load_platform_account("google", "user-two@example.com") == {
        "account_id": "user-two@example.com",
        "user_email": "user-two@example.com",
    }


def test_load_platform_account_reads_legacy_single_account(tmp_creds: Path) -> None:
    save_platform("slack", {"xoxc_token": "tok", "d_cookie": "cookie"})

    assert load_platform_account("slack") == {"xoxc_token": "tok", "d_cookie": "cookie"}
    assert load_platform_accounts("slack") == [{"xoxc_token": "tok", "d_cookie": "cookie"}]


def test_remove_platform_account_updates_default(tmp_creds: Path) -> None:
    upsert_platform_account(
        "google", "user-one@example.com", {"user_email": "user-one@example.com"}
    )
    upsert_platform_account(
        "google", "user-two@example.com", {"user_email": "user-two@example.com"}, make_default=True
    )

    assert remove_platform_account("google", "user-two@example.com") is True

    accounts = load_platform_accounts("google")
    assert [account["account_id"] for account in accounts] == ["user-one@example.com"]
    assert load_platform_account("google") == {
        "account_id": "user-one@example.com",
        "user_email": "user-one@example.com",
    }
    assert remove_platform_account("google", "missing@example.com") is False


def test_remove_platform_account_deletes_final_account(tmp_creds: Path) -> None:
    upsert_platform_account("google", "user@example.com", {"user_email": "user@example.com"})

    assert remove_platform_account("google", "user@example.com") is True
    assert load_platform("google") is None


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
# Google auth verification
# ---------------------------------------------------------------------------


class _FakeGoogleAuthCredentials:
    def __init__(self, *, valid: bool) -> None:
        self.valid = valid


def test_verify_google_auth_missing_returns_missing(tmp_creds: Path) -> None:
    assert verify_google_auth() == ("missing", None)


def test_verify_google_auth_missing_refresh_token_returns_invalid(tmp_creds: Path) -> None:
    save_platform(
        "google",
        GoogleCredentials(
            client_id="id",
            client_secret="secret",
            access_token="tok",
            refresh_token="",
            user_email="user@example.com",
        ),
    )

    status, detail = verify_google_auth()

    assert status == "invalid"
    assert detail is not None
    assert "missing Google refresh token" in detail
    assert "agentgraph auth google" in detail


def test_verify_google_auth_refresh_failure_returns_invalid(
    tmp_creds: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_platform(
        "google",
        GoogleCredentials(
            client_id="id",
            client_secret="secret",
            access_token="tok",
            refresh_token="ref",
            user_email="user@example.com",
        ),
    )

    def _raise_refresh_error() -> Any:
        raise RuntimeError("nope")

    monkeypatch.setattr("agentgraph.auth.google_provider.get_credentials", _raise_refresh_error)

    status, detail = verify_google_auth()

    assert status == "invalid"
    assert detail is not None
    assert "Google refresh token was rejected (RuntimeError)" in detail
    assert "agentgraph auth google" in detail


def test_verify_google_auth_valid_returns_email(
    tmp_creds: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_platform(
        "google",
        GoogleCredentials(
            client_id="id",
            client_secret="secret",
            access_token="tok",
            refresh_token="ref",
            user_email="user@example.com",
        ),
    )
    monkeypatch.setattr(
        "agentgraph.auth.google_provider.get_credentials",
        lambda: _FakeGoogleAuthCredentials(valid=True),
    )

    assert verify_google_auth() == ("ok", "user@example.com")


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
