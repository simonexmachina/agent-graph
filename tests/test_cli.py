"""Tests for CLI structure."""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from agentgraph.auth.credentials import GoogleCredentials, load_platform, save_platform
from agentgraph.cli import app
from agentgraph.connectors.base import ConnectorAccount

runner = CliRunner()


@pytest.fixture
def tmp_creds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    creds_file = tmp_path / "credentials.json"
    monkeypatch.setattr("agentgraph.auth.credentials.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("agentgraph.auth.credentials.CREDENTIALS_FILE", creds_file)
    return creds_file


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "serve" in result.output
    assert "search" in result.output
    assert "auth" in result.output
    assert "download" in result.output
    assert "unify-persons" in result.output


def test_auth_help() -> None:
    result = runner.invoke(app, ["auth", "--help"])
    assert result.exit_code == 0
    assert "status" in result.output.lower()


def test_mcp_config_includes_chatgpt() -> None:
    result = runner.invoke(app, ["mcp-config"])
    assert result.exit_code == 0
    assert "Claude Desktop" in result.output
    assert "Claude Code" in result.output
    assert "ChatGPT" in result.output
    assert "streamable-http" in result.output


class _FakeConnector:
    source = "slack"
    auth_label = "slack"
    auth_description = "Slack"
    onboard_prompt = "Set up Slack?"
    poll_interval = None
    poll_delegates: list[str] = []
    url_patterns: list[str] = []
    auth_called = False

    @classmethod
    def run_auth_flow(cls) -> None:
        cls.auth_called = True

    @classmethod
    def get_authenticated_user(cls) -> None:
        return None


class _FakeGoogleConnector:
    source = "gdocs"
    auth_label = "google"
    auth_description = "Google"
    onboard_prompt = "Set up Google?"
    poll_interval = None
    poll_delegates: list[str] = []
    url_patterns: list[str] = []

    @classmethod
    def run_auth_flow(cls) -> None:
        google_auth = cast(Any, import_module("agentgraph_connector_google.auth"))
        run_oauth_flow = cast(Callable[[], None], google_auth.run_oauth_flow)
        run_oauth_flow()

    @classmethod
    async def verify_auth(cls) -> tuple[str, str | None]:
        return ("ok", "user@example.com")

    @classmethod
    def list_accounts(cls) -> list[ConnectorAccount]:
        return [
            ConnectorAccount(
                account_id="acct-google",
                label="User Example",
                auth_group="google",
                source=cls.source,
                user_id="user@example.com",
                email="user@example.com",
            )
        ]


class _FakeDriveConnector:
    source = "gdrive"
    auth_label = "google"
    auth_description = "Google Drive"
    poll_interval = timedelta(minutes=10)
    poll_delegates = ["gdocs"]
    url_patterns = ["https://drive.google.com/*"]

    @classmethod
    async def verify_auth(cls) -> tuple[str, str | None]:
        return ("ok", "user@example.com")

    @classmethod
    def list_accounts(cls) -> list[ConnectorAccount]:
        return _FakeGoogleConnector.list_accounts()


class _FakeRssConnector:
    source = "rss"
    auth_label = "rss"
    auth_description = "RSS"
    poll_interval = None
    poll_delegates: list[str] = []
    url_patterns: list[str] = []

    @classmethod
    async def verify_auth(cls) -> tuple[str, str | None]:
        return ("missing", None)

    @classmethod
    def cli_help(cls) -> str:
        return "RSS connector help"


class _FakeGoogleToken:
    token = "new-access-token"
    refresh_token = "new-refresh-token"
    expiry = None


class _FakeGoogleFlow:
    captured_client_config: dict[str, Any] | None = None

    def __init__(self) -> None:
        self.credentials = _FakeGoogleToken()

    @classmethod
    def from_client_config(
        cls,
        client_config: dict[str, Any],
        *,
        scopes: list[str],
        redirect_uri: str,
    ) -> _FakeGoogleFlow:
        cls.captured_client_config = client_config
        return cls()

    def authorization_url(self, *, access_type: str, prompt: str) -> tuple[str, None]:
        return ("https://accounts.google.test/auth", None)

    def fetch_token(self, *, code: str) -> None:
        return None


class _FakeUserInfoResponse:
    ok = True

    def json(self) -> dict[str, str]:
        return {"email": "new@example.com", "name": "New User"}


def _fake_requests_get(
    url: str,
    *,
    headers: dict[str, str],
    timeout: int,
) -> _FakeUserInfoResponse:
    return _FakeUserInfoResponse()


def _fake_wait_for_callback(port: int) -> str:
    return "auth-code"


def _fake_webbrowser_open(url: str) -> bool:
    return True


@asynccontextmanager
async def _fake_backend_context() -> AsyncIterator[Any]:
    backend = MagicMock()
    async def _get_platform_last_synced_at(platform: str) -> datetime | None:
        values = {
            "gdocs": datetime(2026, 5, 25, 1, 2, 3, tzinfo=UTC),
            "gdrive": None,
        }
        return values.get(platform)

    backend.get_platform_last_synced_at = AsyncMock(side_effect=_get_platform_last_synced_at)
    yield backend


def test_auth_unknown_target_exits_nonzero() -> None:
    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.connectors.registry.get_all_connectors", return_value=[_FakeConnector()]):
        result = runner.invoke(app, ["auth", "notaplatform"])
    assert result.exit_code != 0
    assert "notaplatform" in result.output


def test_auth_provider_dispatches_to_connector() -> None:
    _FakeConnector.auth_called = False
    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.connectors.registry.get_all_connectors", return_value=[_FakeConnector()]):
        result = runner.invoke(app, ["auth", "slack"])
    assert result.exit_code == 0
    assert _FakeConnector.auth_called


def test_connector_command_dispatches_to_connector() -> None:
    captured: dict[str, object] = {}

    def fake_run_cli_command(args: list[str]) -> dict[str, object]:
        captured["args"] = args
        return {"status": "ok", "args": args}

    _FakeRssConnector.run_cli_command = classmethod(lambda cls, args: fake_run_cli_command(args))

    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.connectors.registry.get_connector", return_value=_FakeRssConnector()):
        result = runner.invoke(app, ["connector", "rss", "add", "https://simonwillison.net/atom/everything/"])

    assert result.exit_code == 0
    assert captured == {"args": ["add", "https://simonwillison.net/atom/everything/"]}
    assert '"status": "ok"' in result.output


def test_connector_command_dispatches_help_to_connector() -> None:
    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.connectors.registry.get_connector", return_value=_FakeRssConnector()):
        result = runner.invoke(app, ["connector", "rss", "--help"])

    assert result.exit_code == 0
    assert result.output == "RSS connector help\n"


def test_connectors_reports_delegated_polling() -> None:
    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.core.runtime.backend_context", _fake_backend_context), \
         patch(
             "agentgraph.connectors.registry.get_all_connectors",
             return_value=[_FakeGoogleConnector(), _FakeDriveConnector()],
         ):
        result = runner.invoke(app, ["connectors"])

    assert result.exit_code == 0
    assert "gdocs" in result.output
    assert "sync: via gdrive poll" in result.output
    assert "sync: polling every 10m for gdocs" in result.output
    assert "last sync: 2026-05-25 01:02:03Z" in result.output
    assert "account:" not in result.output


def test_connectors_json_reports_delegated_polling() -> None:
    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.core.runtime.backend_context", _fake_backend_context), \
         patch(
             "agentgraph.connectors.registry.get_all_connectors",
             return_value=[_FakeGoogleConnector(), _FakeDriveConnector()],
         ):
        result = runner.invoke(app, ["connectors", "--json"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed[0]["auth_provider"] == "google"
    assert parsed[0]["last_synced_at"] == "2026-05-25T01:02:03+00:00"
    assert parsed[0]["polled_by"] == ["gdrive"]
    assert parsed[1]["poll_delegates"] == ["gdocs"]


def test_auth_status_dedupes_shared_google_provider() -> None:
    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch(
             "agentgraph.connectors.registry.get_all_connectors",
             return_value=[_FakeGoogleConnector(), _FakeDriveConnector()],
         ):
        result = runner.invoke(app, ["auth", "status"])

    assert result.exit_code == 0
    assert result.output.count("account: User Example [acct-google]") == 1
    assert "connectors: gdocs, gdrive" in result.output


def test_auth_google_invalid_existing_credentials_reuses_client_config(
    tmp_creds: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_platform(
        "google",
        GoogleCredentials(
            client_id="stored-client-id",
            client_secret="stored-client-secret",
            access_token="old-access-token",
            refresh_token="old-refresh-token",
            user_email="old@example.com",
        ),
    )
    _FakeGoogleFlow.captured_client_config = None

    flow_module = ModuleType("google_auth_oauthlib.flow")
    flow_module.__dict__["Flow"] = _FakeGoogleFlow
    package_module = ModuleType("google_auth_oauthlib")
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib", package_module)
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", flow_module)

    requests_module = ModuleType("requests")
    requests_module.__dict__["get"] = _fake_requests_get
    monkeypatch.setitem(sys.modules, "requests", requests_module)

    monkeypatch.setattr(
        "agentgraph.auth.google_provider.verify_google_auth",
        lambda: ("invalid", "Google refresh token was rejected (RefreshError) - run: agentgraph auth google"),
    )
    monkeypatch.setattr("agentgraph_connector_google.auth._find_free_port", lambda: 9999)
    monkeypatch.setattr("agentgraph_connector_google.auth._wait_for_callback", _fake_wait_for_callback)
    monkeypatch.setattr("webbrowser.open", _fake_webbrowser_open)

    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.connectors.registry.get_all_connectors", return_value=[_FakeGoogleConnector()]):
        result = runner.invoke(app, ["auth", "google"])

    assert result.exit_code == 0
    assert "Google credentials need re-authentication" in result.output
    assert "saved OAuth client ID and secret" in result.output
    assert "Google OAuth client ID" not in result.output
    assert _FakeGoogleFlow.captured_client_config is not None
    installed = _FakeGoogleFlow.captured_client_config["installed"]
    assert installed["client_id"] == "stored-client-id"
    assert installed["client_secret"] == "stored-client-secret"

    saved = load_platform("google")
    assert saved is not None
    assert saved["access_token"] == "new-access-token"
    assert saved["refresh_token"] == "new-refresh-token"


def test_auth_google_valid_credentials_can_skip_reauth(
    tmp_creds: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_platform(
        "google",
        GoogleCredentials(
            client_id="stored-client-id",
            client_secret="stored-client-secret",
            access_token="access-token",
            refresh_token="refresh-token",
            user_email="user@example.com",
        ),
    )
    monkeypatch.setattr(
        "agentgraph.auth.google_provider.verify_google_auth",
        lambda: ("ok", "user@example.com"),
    )

    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.connectors.registry.get_all_connectors", return_value=[_FakeGoogleConnector()]):
        result = runner.invoke(app, ["auth", "google"], input="n\n")

    assert result.exit_code == 0
    assert "Google is already authenticated as user@example.com" in result.output
    assert "Keeping existing credentials" in result.output


def test_search_requires_query() -> None:
    result = runner.invoke(app, ["search"])
    assert result.exit_code != 0
