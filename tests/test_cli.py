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
from agentgraph_connector_google.provider import (
    GOOGLE_OAUTH_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET,
    GoogleCredentials,
)
from typer.testing import CliRunner

from agentgraph.auth.credentials import (
    load_platform,
    load_platform_account,
    load_platform_accounts,
    save_platform,
    upsert_platform_account,
)
from agentgraph.cli import app
from agentgraph.connectors.base import ConnectorAccount, ConnectorCommandEffects
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


def test_unify_persons_shows_the_canonical_person(capsys: pytest.CaptureFixture[str]) -> None:
    from agentgraph.cli_query import cmd_unify_persons

    result: dict[str, Any] = {
        "merged_count": 2,
        "merged_ids": ["duplicate-1", "duplicate-2"],
        "primary": {
            "id": "canonical-person-123",
            "entity_type": "Person",
            "platform": "canonical",
            "platform_entity_id": "simon.wade@gmail.com",
            "title": "Simon Wade",
            "content": "simon.wade@gmail.com",
            "metadata": {"slack_user_id": "T1/U1", "discord_user_id": "D1"},
        },
    }

    with patch("agentgraph.cli_query._post", return_value=result) as post:
        cmd_unify_persons("canonical", ["duplicate-1", "duplicate-2"], as_json=False)

    post.assert_called_once_with(
        "/unify-persons",
        params={"primary": "canonical", "duplicate": ["duplicate-1", "duplicate-2"]},
    )
    output = capsys.readouterr().out
    assert "Unified: 2 duplicate person(s). Canonical person:" in output
    assert "Person — canonical" in output
    assert "Simon Wade" in output
    assert "slack_user_id" in output


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
    from agentgraph.cli_query import FETCH_TIMEOUT, cmd_fetch

    fetch_result = {"entities": 1, "persons": 0, "edges": 0}

    with patch("agentgraph.cli_query._post", return_value=fetch_result) as post:
        cmd_fetch("gsheets", "sheet-id", as_json=True)

    post.assert_called_once_with(
        "/fetch",
        params={"platform": "gsheets", "resource_id": "sheet-id"},
        timeout=FETCH_TIMEOUT,
    )


def test_fetch_entity_uses_extended_server_timeout() -> None:
    from agentgraph.cli_query import FETCH_TIMEOUT, cmd_fetch_entity

    fetch_result = {"entities": 1, "persons": 1, "edges": 1}

    with patch("agentgraph.cli_query._post", return_value=fetch_result) as post:
        cmd_fetch_entity("entity-id", as_json=True)

    post.assert_called_once_with(
        "/fetch-entity",
        params={"entity_id": "entity-id"},
        timeout=FETCH_TIMEOUT,
    )


def test_server_unavailable_exits_nonzero() -> None:
    from agentgraph.cli_query import cmd_query

    with (
        patch("httpx.get", side_effect=httpx.ConnectError("offline")),
        pytest.raises(SystemExit) as exc,
    ):
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
    def run_auth_flow(
        cls,
        account_id: str | None = None,
        add: bool = False,
        args: list[str] | None = None,
    ) -> None:
        google_auth = cast(Any, import_module("agentgraph_connector_google.auth"))
        run_oauth_flow = cast(Callable[..., None], google_auth.run_oauth_flow)
        run_oauth_flow(account_id=account_id, add=add, args=args)

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

    @classmethod
    def command_effects(
        cls,
        args: list[str],
        result: dict[str, Any],
    ) -> ConnectorCommandEffects:
        _ = (args, result)
        return ConnectorCommandEffects()


class _FakeGoogleToken:
    token = "new-access-token"
    refresh_token = "new-refresh-token"
    expiry = None


class _FakeGoogleFlow:
    captured_client_config: dict[str, Any] | None = None
    last_instance: _FakeGoogleFlow | None = None

    def __init__(self) -> None:
        self.credentials = _FakeGoogleToken()
        self.code_verifier = "pkce-verifier"
        self.fetch_token = MagicMock()
        type(self).last_instance = self

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


def _install_fake_google_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeGoogleFlow.last_instance = None
    flow_module = ModuleType("google_auth_oauthlib.flow")
    flow_module.__dict__["Flow"] = _FakeGoogleFlow
    package_module = ModuleType("google_auth_oauthlib")
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib", package_module)
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", flow_module)

    requests_module = ModuleType("requests")
    requests_module.__dict__["get"] = _fake_requests_get
    monkeypatch.setitem(sys.modules, "requests", requests_module)
    monkeypatch.setattr("agentgraph_connector_google.auth._find_free_port", lambda: 9999)
    monkeypatch.setattr(
        "agentgraph_connector_google.auth._wait_for_callback", _fake_wait_for_callback
    )
    monkeypatch.setattr("webbrowser.open", _fake_webbrowser_open)


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
        return {platform: await _get_platform_last_synced_at(platform) for platform in platforms}

    backend.get_platform_last_synced_at = AsyncMock(side_effect=_get_platform_last_synced_at)
    backend.get_platforms_last_synced_at = AsyncMock(side_effect=_get_platforms_last_synced_at)
    yield backend


def test_auth_unknown_target_exits_nonzero() -> None:
    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_all_connectors", return_value=[_FakeConnector()]),
    ):
        result = runner.invoke(app, ["auth", "notaplatform"])
    assert result.exit_code != 0
    assert "notaplatform" in result.output


def test_auth_provider_dispatches_to_connector() -> None:
    _FakeConnector.auth_called = False
    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_all_connectors", return_value=[_FakeConnector()]),
    ):
        result = runner.invoke(app, ["auth", "slack"])
    assert result.exit_code == 0
    assert _FakeConnector.auth_called


def test_auth_slack_accepts_noninteractive_options_after_provider() -> None:
    from agentgraph_connector_slack import SlackConnector

    captured: dict[str, object] = {}

    def fake_cookie_flow(
        *,
        account_id: str | None,
        add: bool,
        xoxc_token: str | None,
        d_cookie: str | None,
    ) -> None:
        captured.update(
            account_id=account_id,
            add=add,
            xoxc_token=xoxc_token,
            d_cookie=d_cookie,
        )

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_all_connectors", return_value=[SlackConnector()]),
        patch("agentgraph_connector_slack.auth.run_cookie_flow", side_effect=fake_cookie_flow),
    ):
        result = runner.invoke(
            app,
            [
                "auth",
                "slack",
                "--xoxc-token",
                "xoxc-test",
                "--d-cookie",
                "cookie",
                "--account",
                "slack:T1:U1",
                "--add",
            ],
        )

    assert result.exit_code == 0
    assert captured == {
        "account_id": "slack:T1:U1",
        "add": True,
        "xoxc_token": "xoxc-test",
        "d_cookie": "cookie",
    }


def test_auth_remove_deletes_provider_credentials(tmp_creds: Path) -> None:
    save_platform("slack", {"xoxc_token": "xoxc-test", "d_cookie": "cookie"})

    result = runner.invoke(app, ["auth", "remove", "slack"])

    assert result.exit_code == 0
    assert result.output == "Removed stored credentials for slack.\n"
    assert load_platform("slack") is None


def test_auth_remove_account_outputs_json(tmp_creds: Path) -> None:
    upsert_platform_account("google", "one@example.com", {"user_email": "one@example.com"})
    upsert_platform_account("google", "two@example.com", {"user_email": "two@example.com"})

    result = runner.invoke(
        app, ["auth", "remove", "google", "--account", "one@example.com", "--json"]
    )

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed == {
        "provider": "google",
        "removed": True,
        "account_id": "one@example.com",
    }
    assert [account["account_id"] for account in load_platform_accounts("google")] == [
        "two@example.com"
    ]
    assert load_platform_account("google", "two@example.com") is not None


def test_auth_status_reports_corrupt_credentials_file(tmp_creds: Path) -> None:
    save_platform("slack", {"xoxc_token": "xoxc-test"})
    tmp_creds.write_text(tmp_creds.read_text() + '  "discord": {')

    result = runner.invoke(app, ["auth", "status"])

    assert result.exit_code == 1
    assert "Could not parse" in result.output
    assert str(tmp_creds) in result.output


def test_auth_remove_reports_corrupt_credentials_file(tmp_creds: Path) -> None:
    tmp_creds.write_text("{not json")

    result = runner.invoke(app, ["auth", "remove", "slack"])

    assert result.exit_code == 1
    assert "Could not parse" in result.output


def test_auth_remove_missing_provider_exits_nonzero() -> None:
    result = runner.invoke(app, ["auth", "remove", "slack"])

    assert result.exit_code != 0
    assert "No stored credentials found for slack." in result.output


def test_connector_command_dispatches_to_connector() -> None:
    captured: dict[str, object] = {}

    class _DispatchRssConnector(_FakeRssConnector):
        @classmethod
        def run_cli_command(cls, args: list[str]) -> dict[str, object]:
            captured["args"] = args
            return {"status": "ok", "args": args}

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_connector", return_value=_DispatchRssConnector()),
    ):
        result = runner.invoke(
            app, ["connector", "rss", "add", "https://simonwillison.net/atom/everything/"]
        )

    assert result.exit_code == 0
    assert captured == {"args": ["add", "https://simonwillison.net/atom/everything/"]}
    assert result.output == "formatted ok\n"


def test_connector_command_json_outputs_raw_result() -> None:
    class _JsonRssConnector(_FakeRssConnector):
        @classmethod
        def run_cli_command(cls, args: list[str]) -> dict[str, object]:
            return {"status": "ok", "args": args}

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_connector", return_value=_JsonRssConnector()),
    ):
        result = runner.invoke(
            app, ["connector", "rss", "add", "https://example.com/feed.xml", "--json"]
        )

    assert result.exit_code == 0
    assert '"status": "ok"' in result.output
    assert '"args": [' in result.output


def test_connector_command_queues_requested_poll() -> None:
    class _PollingRssConnector(_FakeRssConnector):
        @classmethod
        def run_cli_command(cls, args: list[str]) -> dict[str, Any]:
            return {"status": "ok", "args": args}

        @classmethod
        def command_effects(
            cls,
            args: list[str],
            result: dict[str, Any],
        ) -> ConnectorCommandEffects:
            _ = (args, result)
            return ConnectorCommandEffects(poll=True)

    poll_result = {"source": "rss", "status": "queued", "reason": None}
    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_connector", return_value=_PollingRssConnector()),
        patch("agentgraph.cli_query.queue_connector_poll", return_value=poll_result) as queue_poll,
    ):
        result = runner.invoke(
            app, ["connector", "rss", "add", "https://example.com/feed.xml", "--json"]
        )

    assert result.exit_code == 0
    assert json.loads(result.output)["poll"] == poll_result
    queue_poll.assert_called_once_with("rss")


def test_connector_command_does_not_poll_after_validation_error() -> None:
    class _InvalidRssConnector(_FakeRssConnector):
        @classmethod
        def run_cli_command(cls, args: list[str]) -> dict[str, Any]:
            _ = args
            raise ValueError("Not a valid RSS/Atom feed")

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_connector", return_value=_InvalidRssConnector()),
        patch("agentgraph.cli_query.queue_connector_poll") as queue_poll,
    ):
        result = runner.invoke(app, ["connector", "rss", "add", "https://example.com/not-a-feed"])

    assert result.exit_code == 1
    assert "Not a valid RSS/Atom feed" in result.output
    queue_poll.assert_not_called()


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            {"polled": ["rss"], "already_running": [], "skipped": []},
            {"source": "rss", "status": "queued", "reason": None},
        ),
        (
            {"polled": [], "already_running": ["rss"], "skipped": []},
            {"source": "rss", "status": "already_running", "reason": None},
        ),
        (
            {
                "polled": [],
                "already_running": [],
                "skipped": [{"source": "rss", "reason": "authentication missing"}],
            },
            {"source": "rss", "status": "skipped", "reason": "authentication missing"},
        ),
    ],
)
def test_queue_connector_poll_normalizes_server_result(
    response: dict[str, object],
    expected: dict[str, object],
) -> None:
    from agentgraph.cli_query import queue_connector_poll

    with patch("agentgraph.cli_query._post", return_value=response):
        result = queue_connector_poll("rss")

    assert result == expected


def test_connector_command_dispatches_help_to_connector() -> None:
    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_connector", return_value=_FakeRssConnector()),
    ):
        result = runner.invoke(app, ["connector", "rss", "--help"])

    assert result.exit_code == 0
    assert result.output == "RSS connector help\n"


def test_connectors_reports_delegated_polling() -> None:
    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.core.runtime.backend_context", _fake_backend_context),
        patch(
            "agentgraph.connectors.registry.get_all_connectors",
            return_value=[_FakeGoogleConnector(), _FakeDriveConnector()],
        ),
    ):
        result = runner.invoke(app, ["connectors"])

    assert result.exit_code == 0
    assert "gdocs" in result.output
    assert "sync: via gdrive poll" in result.output
    assert "sync: polling every 10m for gdocs" in result.output
    assert "last sync: 2026-05-25 01:02:03Z" in result.output
    assert "account:" not in result.output


def test_connectors_json_reports_delegated_polling() -> None:
    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.core.runtime.backend_context", _fake_backend_context),
        patch(
            "agentgraph.connectors.registry.get_all_connectors",
            return_value=[_FakeGoogleConnector(), _FakeDriveConnector()],
        ),
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

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.core.runtime.backend_context", _fake_backend_context),
        patch(
            "agentgraph.connectors.registry.get_all_connectors", return_value=[_LocalConnector()]
        ),
    ):
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

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.core.runtime.backend_context", _fake_backend_context),
        patch(
            "agentgraph.connectors.registry.get_all_connectors", return_value=[_VerifiedConnector()]
        ),
    ):
        result = runner.invoke(app, ["connectors", "--verify", "--json"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed[0]["auth_status"] == "invalid"
    assert parsed[0]["auth_detail"] == "live check failed"
    assert parsed[0]["auth_verified"] is True
    assert _VerifiedConnector.verify_called is True


def test_connectors_omits_auth_status_for_non_auth_connectors() -> None:
    class _NonAuthRssConnector(_FakeRssConnector):
        verify_called = False

        @classmethod
        async def verify_auth(cls) -> tuple[str, str | None]:
            cls.verify_called = True
            return ("ok", "should not be called")

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.core.runtime.backend_context", _fake_backend_context),
        patch(
            "agentgraph.connectors.registry.get_all_connectors",
            return_value=[_NonAuthRssConnector()],
        ),
    ):
        json_result = runner.invoke(app, ["connectors", "--verify", "--json"])
        text_result = runner.invoke(app, ["connectors", "--verify"])

    assert json_result.exit_code == 0
    parsed = json.loads(json_result.output)
    assert parsed[0]["source"] == "rss"
    assert parsed[0]["auth_provider"] is None
    assert parsed[0]["auth_status"] is None
    assert parsed[0]["auth_detail"] is None
    assert parsed[0]["auth_verified"] is False
    assert parsed[0]["account_count"] == 0
    assert text_result.exit_code == 0
    assert "rss" in text_result.output
    assert "auth:" not in text_result.output
    assert "sync:" in text_result.output
    assert _NonAuthRssConnector.verify_called is False


def test_auth_status_dedupes_shared_google_provider() -> None:
    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch(
            "agentgraph.connectors.registry.get_all_connectors",
            return_value=[_FakeGoogleConnector(), _FakeDriveConnector()],
        ),
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

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch(
            "agentgraph.connectors.registry.get_all_connectors",
            return_value=[_FakeGoogleConnector(), _FakeRssConnector(), _FakeWebConnector()],
        ),
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
        "agentgraph_connector_google.auth.verify_google_auth",
        lambda: (
            "invalid",
            "Google refresh token was rejected (RefreshError) - run: agentgraph auth google",
        ),
    )
    monkeypatch.setattr("agentgraph_connector_google.auth._find_free_port", lambda: 9999)
    monkeypatch.setattr(
        "agentgraph_connector_google.auth._wait_for_callback", _fake_wait_for_callback
    )
    monkeypatch.setattr("webbrowser.open", _fake_webbrowser_open)

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch(
            "agentgraph.connectors.registry.get_all_connectors",
            return_value=[_FakeGoogleConnector()],
        ),
    ):
        result = runner.invoke(app, ["auth", "google"])

    assert result.exit_code == 0
    assert "Google credentials need re-authentication" in result.output
    assert "packaged OAuth client" in result.output
    assert "Google OAuth client ID" not in result.output
    assert _FakeGoogleFlow.captured_client_config is not None
    installed = _FakeGoogleFlow.captured_client_config["installed"]
    assert installed["client_id"] == GOOGLE_OAUTH_CLIENT_ID
    assert installed["client_secret"] == GOOGLE_OAUTH_CLIENT_SECRET

    saved = load_platform("google")
    assert saved is not None
    assert saved["access_token"] == "new-access-token"
    assert saved["refresh_token"] == "new-refresh-token"


def test_auth_google_uses_packaged_client_without_prompt(
    tmp_creds: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeGoogleFlow.captured_client_config = None
    _install_fake_google_oauth(monkeypatch)

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch(
            "agentgraph.connectors.registry.get_all_connectors",
            return_value=[_FakeGoogleConnector()],
        ),
    ):
        result = runner.invoke(app, ["auth", "google"])

    assert result.exit_code == 0
    assert "Google OAuth client" not in result.output
    assert _FakeGoogleFlow.captured_client_config is not None
    installed = _FakeGoogleFlow.captured_client_config["installed"]
    assert installed["client_id"] == GOOGLE_OAUTH_CLIENT_ID
    assert installed["client_secret"] == GOOGLE_OAUTH_CLIENT_SECRET
    assert _FakeGoogleFlow.last_instance is not None
    _FakeGoogleFlow.last_instance.fetch_token.assert_called_once_with(code="auth-code")
    saved = load_platform("google")
    assert saved is not None
    assert saved["client_id"] == GOOGLE_OAUTH_CLIENT_ID
    assert "client_secret" not in saved


def test_auth_google_rejects_client_id_override() -> None:
    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch(
            "agentgraph.connectors.registry.get_all_connectors",
            return_value=[_FakeGoogleConnector()],
        ),
    ):
        result = runner.invoke(
            app,
            ["auth", "google", "--client-id", "override-client-id"],
        )

    assert result.exit_code == 2
    assert "unrecognized arguments: --client-id override-client-id" in result.output


def test_auth_google_rejects_unknown_provider_option() -> None:
    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch(
            "agentgraph.connectors.registry.get_all_connectors",
            return_value=[_FakeGoogleConnector()],
        ),
    ):
        result = runner.invoke(app, ["auth", "google", "--unknown"])

    assert result.exit_code == 2
    assert "unrecognized arguments: --unknown" in result.output


def test_auth_google_valid_credentials_can_skip_reauth(
    tmp_creds: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_platform(
        "google",
        GoogleCredentials(
            client_id="stored-client-id",
            access_token="access-token",
            refresh_token="refresh-token",
            user_email="user@example.com",
        ),
    )
    monkeypatch.setattr(
        "agentgraph_connector_google.auth.verify_google_auth",
        lambda: ("ok", "user@example.com"),
    )

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch(
            "agentgraph.connectors.registry.get_all_connectors",
            return_value=[_FakeGoogleConnector()],
        ),
    ):
        result = runner.invoke(app, ["auth", "google"], input="n\n")

    assert result.exit_code == 0
    assert "Google is already authenticated as user@example.com" in result.output
    assert "Keeping existing credentials" in result.output


def test_search_requires_query() -> None:
    result = runner.invoke(app, ["search"])
    assert result.exit_code != 0
