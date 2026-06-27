"""Tests for CLI structure."""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from typer.testing import CliRunner

from agentgraph.auth.credentials import GoogleCredentials, load_platform, save_platform
from agentgraph.cli import app
from agentgraph.connectors.base import ConnectorAccount
from agentgraph.core.storage import EntityResult

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
    assert "bookmark" in result.output
    assert "delete" in result.output
    assert "unify-persons" in result.output


def test_bookmark_command_dispatches_to_cli_query() -> None:
    with patch("agentgraph.cli_query.cmd_bookmark") as cmd_bookmark:
        result = runner.invoke(app, ["bookmark", "abc123", "--json"])

    assert result.exit_code == 0
    cmd_bookmark.assert_called_once_with(target="abc123", bookmarked=True, as_json=True)


def test_bookmark_remove_command_dispatches_to_cli_query() -> None:
    with patch("agentgraph.cli_query.cmd_bookmark") as cmd_bookmark:
        result = runner.invoke(app, ["bookmark", "abc123", "--remove", "--json"])

    assert result.exit_code == 0
    cmd_bookmark.assert_called_once_with(target="abc123", bookmarked=False, as_json=True)


def test_delete_command_dispatches_to_cli_query() -> None:
    with patch("agentgraph.cli_query.cmd_delete") as cmd_delete:
        result = runner.invoke(app, ["delete", "abc123", "--json"])

    assert result.exit_code == 0
    cmd_delete.assert_called_once_with(target="abc123", as_json=True)


def test_get_url_uses_entity_by_url_endpoint() -> None:
    from agentgraph.cli_query import cmd_get

    entity: EntityResult = {
        "id": "entity-12345678",
        "entity_type": "Document",
        "platform": "web",
        "title": "Page",
        "metadata": {},
    }

    with patch("agentgraph.cli_query._get", return_value=entity) as get:
        cmd_get("https://example.com/page", as_json=True)

    get.assert_called_once_with("/entity-by-url", {"url": "https://example.com/page"})


def test_get_url_reports_not_found_from_server() -> None:
    from agentgraph.cli_query import cmd_get

    response = httpx.Response(
        404,
        json={"detail": "Entity not found"},
        request=httpx.Request("GET", "http://127.0.0.1:8765/api/cli/entity-by-url"),
    )
    error = httpx.HTTPStatusError("not found", request=response.request, response=response)

    with patch("agentgraph.cli_query._get", side_effect=error):
        cmd_get("https://example.com/page", as_json=True)


def test_get_prints_raw_content_without_rich_markup_errors() -> None:
    from agentgraph.cli_query import cmd_get

    entity = {
        "id": "entity-12345678",
        "entity_type": "Document",
        "platform": "web",
        "title": "Page [literal]",
        "content": "window.DD_RUM.init({allowedTracingUrls: [/https?:\\/\\/(.+\\/.)?substack(cdn)?\\.com/]});",
        "metadata": {"pattern": "[/not-rich-markup]"},
    }

    with patch("agentgraph.cli_query._get", return_value=entity):
        cmd_get("entity-12345678", as_json=False)


def test_bookmark_uses_server_endpoint() -> None:
    from agentgraph.cli_query import cmd_bookmark

    entity = {
        "id": "entity-12345678",
        "title": "Bookmarked",
        "platform_entity_id": "ref",
        "bookmarked": True,
    }

    with patch("agentgraph.cli_query._post", return_value=entity) as post:
        cmd_bookmark("https://example.com/page", bookmarked=True, as_json=True)

    post.assert_called_once_with(
        "/bookmark",
        params={"target": "https://example.com/page", "bookmarked": True},
    )


def test_delete_uses_server_endpoint() -> None:
    from agentgraph.cli_query import cmd_delete

    result = {
        "deleted": True,
        "entity": {
            "id": "entity-12345678",
            "title": "Deleted",
            "platform_entity_id": "ref",
        },
    }

    with patch("agentgraph.cli_query._post", return_value=result) as post:
        cmd_delete("abc123", as_json=True)

    post.assert_called_once_with("/delete", params={"target": "abc123"})


def test_query_exits_when_server_unavailable() -> None:
    from agentgraph.cli_query import cmd_query

    with patch("agentgraph.cli_query._get", side_effect=SystemExit(1)), pytest.raises(SystemExit):
        cmd_query(
            entity_type="Thread",
            filters={},
            limit=5,
            order_by="updated_at",
            since=None,
            authored_by_me=False,
            as_json=True,
        )


def test_download_uses_server_endpoint() -> None:
    from agentgraph.cli_query import cmd_download

    result = {
        "filename": "sheet.xlsx",
        "bytes": 123,
        "path": "/tmp/sheet.xlsx",
    }

    with patch("agentgraph.cli_query._post", return_value=result) as post:
        cmd_download("gsheets/sheet-id", output_path="/tmp", as_json=True)

    post.assert_called_once_with(
        "/download",
        params={"entity_id": "gsheets/sheet-id", "output_path": "/tmp"},
    )


def test_fetch_uses_server_endpoint() -> None:
    from agentgraph.cli_query import cmd_fetch

    fetch_result = {"entities": 1, "persons": 0, "edges": 0}

    with patch("agentgraph.cli_query._post", return_value=fetch_result) as post:
        cmd_fetch("gsheets", "sheet-id", as_json=True)

    post.assert_called_once_with(
        "/fetch",
        params={"platform": "gsheets", "resource_id": "sheet-id"},
    )


def test_server_unavailable_exits_nonzero() -> None:
    from agentgraph.cli_query import cmd_query

    with patch("httpx.get", side_effect=httpx.ConnectError("offline")), pytest.raises(SystemExit) as exc:
        cmd_query(
            entity_type="Thread",
            filters={},
            limit=5,
            order_by="updated_at",
            since=None,
            authored_by_me=False,
            as_json=True,
        )

    assert exc.value.code == 1


def test_cli_server_requests_use_short_connect_timeout() -> None:
    from agentgraph.cli_query import cmd_query

    response = httpx.Response(
        200,
        json=[],
        request=httpx.Request("GET", "http://127.0.0.1:8765/api/cli/query"),
    )

    with patch("httpx.get", return_value=response) as get:
        cmd_query(
            entity_type="Thread",
            filters={},
            limit=5,
            order_by="updated_at",
            since=None,
            authored_by_me=False,
            as_json=True,
        )

    timeout = get.call_args.kwargs["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 0.5
    assert timeout.read == 10


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
    assert "do not use the stdio JSON" in result.output
    assert "http://127.0.0.1:8808/mcp" in result.output
    assert "https://your-tunnel.example/mcp" in result.output


def test_install_skill_defaults_to_user_agents_skills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    result = runner.invoke(app, ["install-skill"])

    assert result.exit_code == 0
    skill_path = home / ".agents" / "skills" / "graph" / "SKILL.md"
    assert skill_path.is_file()
    assert "AgentGraph CLI skill" in skill_path.read_text(encoding="utf-8")
    assert str(skill_path.parent) in result.output


def test_install_skill_refuses_to_overwrite_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    skill_path = home / ".agents" / "skills" / "graph" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("custom", encoding="utf-8")

    result = runner.invoke(app, ["install-skill"])

    assert result.exit_code == 1
    assert "Use --force" in result.output
    assert skill_path.read_text(encoding="utf-8") == "custom"


def test_install_skill_force_overwrites_existing_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    skill_path = home / ".agents" / "skills" / "graph" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("custom", encoding="utf-8")

    result = runner.invoke(app, ["install-skill", "--force", "--json"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["skill"] == "graph"
    assert parsed["target"] == "user"
    assert parsed["overwritten"] is True
    assert "AgentGraph CLI skill" in skill_path.read_text(encoding="utf-8")


def test_install_skill_project_target_uses_current_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["install-skill", "--target", "project"])

    assert result.exit_code == 0
    assert (tmp_path / ".agents" / "skills" / "graph" / "SKILL.md").is_file()


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
    appears_in_auth_status = False
    poll_interval = None
    poll_delegates: list[str] = []
    url_patterns: list[str] = []

    @classmethod
    async def verify_auth(cls) -> tuple[str, str | None]:
        return ("missing", None)

    @classmethod
    def cli_help(cls) -> str:
        return "RSS connector help"

    @classmethod
    def format_cli_result(cls, result: dict[str, Any]) -> str:
        return f"formatted {result['status']}"


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
async def _fake_backend_context() -> AsyncGenerator[Any, None]:
    backend = MagicMock()
    async def _get_platform_last_synced_at(platform: str) -> datetime | None:
        values = {
            "gdocs": datetime(2026, 5, 25, 1, 2, 3, tzinfo=UTC),
            "gdrive": None,
        }
        return values.get(platform)

    async def _get_platforms_last_synced_at(platforms: list[str]) -> dict[str, datetime | None]:
        return {
            platform: await _get_platform_last_synced_at(platform)
            for platform in platforms
        }

    backend.get_platform_last_synced_at = AsyncMock(side_effect=_get_platform_last_synced_at)
    backend.get_platforms_last_synced_at = AsyncMock(side_effect=_get_platforms_last_synced_at)
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

    class _DispatchRssConnector(_FakeRssConnector):
        @classmethod
        def run_cli_command(cls, args: list[str]) -> dict[str, object]:
            captured["args"] = args
            return {"status": "ok", "args": args}

    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.connectors.registry.get_connector", return_value=_DispatchRssConnector()):
        result = runner.invoke(app, ["connector", "rss", "add", "https://simonwillison.net/atom/everything/"])

    assert result.exit_code == 0
    assert captured == {"args": ["add", "https://simonwillison.net/atom/everything/"]}
    assert result.output == "formatted ok\n"


def test_connector_command_json_outputs_raw_result() -> None:
    class _JsonRssConnector(_FakeRssConnector):
        @classmethod
        def run_cli_command(cls, args: list[str]) -> dict[str, object]:
            return {"status": "ok", "args": args}

    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.connectors.registry.get_connector", return_value=_JsonRssConnector()):
        result = runner.invoke(app, ["connector", "rss", "add", "https://example.com/feed.xml", "--json"])

    assert result.exit_code == 0
    assert '"status": "ok"' in result.output
    assert '"args": [' in result.output


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


def test_connectors_default_uses_local_auth_status_without_live_verify() -> None:
    class _LocalConnector(_FakeGoogleConnector):
        verify_called = False

        @classmethod
        async def verify_auth(cls) -> tuple[str, str | None]:
            cls.verify_called = True
            return ("invalid", "live check failed")

    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.core.runtime.backend_context", _fake_backend_context), \
         patch("agentgraph.connectors.registry.get_all_connectors", return_value=[_LocalConnector()]):
        result = runner.invoke(app, ["connectors", "--json"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed[0]["auth_status"] == "ok"
    assert parsed[0]["auth_verified"] is False
    assert _LocalConnector.verify_called is False


def test_connectors_verify_runs_live_auth_check() -> None:
    class _VerifiedConnector(_FakeGoogleConnector):
        verify_called = False

        @classmethod
        async def verify_auth(cls) -> tuple[str, str | None]:
            cls.verify_called = True
            return ("invalid", "live check failed")

    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.core.runtime.backend_context", _fake_backend_context), \
         patch("agentgraph.connectors.registry.get_all_connectors", return_value=[_VerifiedConnector()]):
        result = runner.invoke(app, ["connectors", "--verify", "--json"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed[0]["auth_status"] == "invalid"
    assert parsed[0]["auth_detail"] == "live check failed"
    assert parsed[0]["auth_verified"] is True
    assert _VerifiedConnector.verify_called is True


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


def test_auth_status_excludes_non_auth_connectors() -> None:
    class _FakeWebConnector:
        source = "web"
        auth_label = None
        auth_description = "Web"
        appears_in_auth_status = False
        poll_interval = None
        poll_delegates: list[str] = []
        url_patterns: list[str] = []

    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch(
             "agentgraph.connectors.registry.get_all_connectors",
             return_value=[_FakeGoogleConnector(), _FakeRssConnector(), _FakeWebConnector()],
         ):
        result = runner.invoke(app, ["auth", "--json", "status"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert [item["provider"] for item in parsed] == ["google"]


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
