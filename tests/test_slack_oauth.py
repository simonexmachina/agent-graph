"""Slack OAuth credential and token lifecycle tests."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from agentgraph_connector_slack import SlackConnector, _api_get
from agentgraph_connector_slack.auth import (
    DEFAULT_REDIRECT_URI,
    OPTIONAL_SCOPES,
    REQUIRED_SCOPES,
    SlackBrowserCredentials,
    SlackOAuthCallback,
    SlackOAuthCredentials,
    _admin_setup_instructions,
    _authorization_instructions,
    _available_oauth_client_id,
    _member_missing_workspace_instructions,
    _member_visible_workspace_instructions,
    load_slack_creds,
    refresh_oauth_credentials,
    run_guided_oauth_flow,
    run_interactive_auth_flow,
    run_oauth_flow,
    slack_headers,
    validate_required_scopes,
)

from agentgraph.auth.credentials import load_platform_account, save_platform


@pytest.fixture
def tmp_creds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    credentials_file = tmp_path / "credentials.json"
    monkeypatch.setattr("agentgraph.auth.credentials.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("agentgraph.auth.credentials.CREDENTIALS_FILE", credentials_file)
    return credentials_file


def _oauth_record(*, expires_at: datetime | None = None) -> dict[str, Any]:
    return {
        "auth_method": "oauth",
        "access_token": "xoxe.xoxp-old",
        "refresh_token": "xoxe-refresh-old",
        "expires_at": expires_at or datetime.now(UTC) + timedelta(hours=12),
        "client_id": "123.456",
        "scopes": sorted(REQUIRED_SCOPES | OPTIONAL_SCOPES),
        "user_id": "U1",
        "team_id": "T1",
        "team_name": "Example",
        "account_id": "slack:T1:U1",
    }


def test_legacy_credentials_infer_browser_method(tmp_creds: Path) -> None:
    save_platform("slack", {
        "xoxc_token": "xoxc-T1-old",
        "d_cookie": "cookie",
        "user_id": "U1",
        "team_id": "T1",
    })

    credentials = load_slack_creds()

    assert isinstance(credentials, SlackBrowserCredentials)
    assert credentials.auth_method == "browser"


def test_oauth_credentials_use_discriminator(tmp_creds: Path) -> None:
    save_platform("slack", _oauth_record())

    credentials = load_slack_creds()

    assert isinstance(credentials, SlackOAuthCredentials)
    assert credentials.client_id == "123.456"


def test_required_scope_validation_ignores_optional_email() -> None:
    assert validate_required_scopes(sorted(REQUIRED_SCOPES)) == []
    assert validate_required_scopes(sorted(REQUIRED_SCOPES - {"groups:read"})) == [
        "groups:read"
    ]


@pytest.mark.asyncio
async def test_headers_are_bearer_only_for_oauth_and_include_cookie_for_browser(
    tmp_creds: Path,
) -> None:
    save_platform("slack", _oauth_record())
    oauth_headers = await slack_headers()
    save_platform("slack", {"xoxc_token": "xoxc-T1", "d_cookie": "cookie"})
    browser_headers = await slack_headers()

    assert oauth_headers == {
        "Authorization": "Bearer xoxe.xoxp-old",
        "Content-Type": "application/json",
    }
    assert browser_headers["Authorization"] == "Bearer xoxc-T1"
    assert browser_headers["Cookie"] == "d=cookie"


@pytest.mark.asyncio
async def test_headers_select_mixed_method_accounts(tmp_creds: Path) -> None:
    from agentgraph.auth.credentials import upsert_platform_account

    upsert_platform_account("slack", "slack:T1:U1", _oauth_record())
    upsert_platform_account(
        "slack",
        "slack:T2:U2",
        SlackBrowserCredentials(
            xoxc_token="xoxc-T2", d_cookie="cookie-2", team_id="T2", user_id="U2"
        ),
    )

    oauth_headers = await slack_headers("slack:T1:U1")
    browser_headers = await slack_headers("slack:T2:U2")

    assert oauth_headers["Authorization"] == "Bearer xoxe.xoxp-old"
    assert "Cookie" not in oauth_headers
    assert browser_headers["Authorization"] == "Bearer xoxc-T2"
    assert browser_headers["Cookie"] == "d=cookie-2"


@pytest.mark.asyncio
async def test_proactive_refresh_persists_rotated_tokens(tmp_creds: Path) -> None:
    save_platform("slack", _oauth_record(expires_at=datetime.now(UTC) + timedelta(minutes=4)))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={
            "ok": True,
            "access_token": "xoxe.xoxp-new",
            "refresh_token": "xoxe-refresh-new",
            "expires_in": 43200,
            "scope": ",".join(sorted(REQUIRED_SCOPES)),
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        headers = await slack_headers("slack:T1:U1", client=client)

    stored = load_platform_account("slack", "slack:T1:U1")
    assert headers["Authorization"] == "Bearer xoxe.xoxp-new"
    assert stored is not None
    assert stored["access_token"] == "xoxe.xoxp-new"
    assert stored["refresh_token"] == "xoxe-refresh-new"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_concurrent_refresh_is_coalesced(tmp_creds: Path) -> None:
    save_platform("slack", _oauth_record(expires_at=datetime.now(UTC)))
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return httpx.Response(200, json={
            "ok": True,
            "access_token": "new-token",
            "refresh_token": "new-refresh",
            "expires_in": 43200,
            "scope": ",".join(sorted(REQUIRED_SCOPES)),
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first, second = await asyncio.gather(
            refresh_oauth_credentials("slack:T1:U1", client=client),
            refresh_oauth_credentials("slack:T1:U1", client=client),
        )

    assert first.access_token == second.access_token == "new-token"
    assert calls == 1


@pytest.mark.asyncio
async def test_concurrent_forced_refresh_reuses_first_rotation(tmp_creds: Path) -> None:
    save_platform("slack", _oauth_record())
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return httpx.Response(200, json={
            "ok": True,
            "access_token": "forced-token",
            "refresh_token": "forced-refresh",
            "expires_in": 43200,
            "scope": ",".join(sorted(REQUIRED_SCOPES)),
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first, second = await asyncio.gather(
            refresh_oauth_credentials("slack:T1:U1", force=True, client=client),
            refresh_oauth_credentials("slack:T1:U1", force=True, client=client),
        )

    assert first.access_token == second.access_token == "forced-token"
    assert calls == 1


@pytest.mark.asyncio
async def test_refresh_failure_keeps_existing_tokens(tmp_creds: Path) -> None:
    save_platform("slack", _oauth_record(expires_at=datetime.now(UTC)))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "invalid_refresh_token"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="invalid_refresh_token"):
            await refresh_oauth_credentials("slack:T1:U1", client=client)

    stored = load_platform_account("slack", "slack:T1:U1")
    assert stored is not None
    assert stored["access_token"] == "xoxe.xoxp-old"


@pytest.mark.asyncio
async def test_api_retries_once_after_token_expired(tmp_creds: Path) -> None:
    save_platform("slack", _oauth_record())
    api_calls = 0
    refresh_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls, refresh_calls
        if request.url.path.endswith("oauth.v2.user.access"):
            refresh_calls += 1
            return httpx.Response(200, json={
                "ok": True,
                "access_token": "refreshed-token",
                "refresh_token": "refreshed-refresh",
                "expires_in": 43200,
                "scope": ",".join(sorted(REQUIRED_SCOPES)),
            })
        api_calls += 1
        if api_calls == 1:
            return httpx.Response(200, json={"ok": False, "error": "token_expired"})
        assert request.headers["authorization"] == "Bearer refreshed-token"
        return httpx.Response(200, json={"ok": True, "channels": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _api_get(client, "conversations.list", account_id="slack:T1:U1")

    assert result["ok"] is True
    assert api_calls == 2
    assert refresh_calls == 1


def _exchange_result(scopes: set[str] | frozenset[str] = REQUIRED_SCOPES) -> dict[str, Any]:
    return {
        "ok": True,
        "access_token": "oauth-access",
        "refresh_token": "oauth-refresh",
        "expires_in": 43200,
        "scope": ",".join(sorted(scopes)),
        "authed_user": {"id": "U1"},
        "team": {"id": "T1", "name": "Example"},
    }


def test_oauth_flow_uses_pkce_state_and_default_redirect(
    tmp_creds: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTGRAPH_SLACK_CLIENT_ID", "123.456")
    monkeypatch.setenv(
        "AGENTGRAPH_SLACK_REDIRECT_URI",
        "http://localhost:9999/unsupported",
    )
    opened: list[str] = []
    exchange = MagicMock(return_value=_exchange_result())

    with (
        patch("agentgraph_connector_slack.auth._pkce_pair", return_value=("verifier", "challenge")),
        patch("agentgraph_connector_slack.auth.secrets.token_urlsafe", return_value="state-value"),
        patch(
            "agentgraph_connector_slack.auth._wait_for_oauth_callback",
            return_value=SlackOAuthCallback(code="code", state="state-value"),
        ) as wait,
        patch("agentgraph_connector_slack.auth._exchange_oauth_code", exchange),
        patch("agentgraph_connector_slack.auth.webbrowser.open", side_effect=opened.append),
    ):
        run_oauth_flow()

    query = parse_qs(urlparse(opened[0]).query)
    assert urlparse(opened[0]).path == "/oauth/v2_user/authorize"
    assert query["code_challenge"] == ["challenge"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == ["state-value"]
    assert query["redirect_uri"] == [DEFAULT_REDIRECT_URI]
    wait.assert_called_once_with(DEFAULT_REDIRECT_URI)
    exchange.assert_called_once_with(
        code="code",
        verifier="verifier",
        client_id="123.456",
        redirect_uri=DEFAULT_REDIRECT_URI,
    )
    stored = load_platform_account("slack", "slack:T1:U1")
    assert stored is not None
    assert stored["auth_method"] == "oauth"
    assert stored["client_id"] == "123.456"


@pytest.mark.parametrize(
    ("callback", "error"),
    [
        (SlackOAuthCallback(error="access_denied", state="state-value"), "denied"),
        (SlackOAuthCallback(code="code", state="wrong"), "state did not match"),
    ],
)
def test_oauth_flow_rejects_denial_and_state_mismatch(
    tmp_creds: Path,
    monkeypatch: pytest.MonkeyPatch,
    callback: SlackOAuthCallback,
    error: str,
) -> None:
    monkeypatch.setenv("AGENTGRAPH_SLACK_CLIENT_ID", "123.456")
    with (
        patch("agentgraph_connector_slack.auth.secrets.token_urlsafe", return_value="state-value"),
        patch("agentgraph_connector_slack.auth._wait_for_oauth_callback", return_value=callback),
        patch("agentgraph_connector_slack.auth.webbrowser.open"),
        patch("agentgraph_connector_slack.auth._exchange_oauth_code") as exchange,
        pytest.raises(RuntimeError, match=error),
    ):
        run_oauth_flow()
    exchange.assert_not_called()


def test_oauth_denial_still_requires_matching_state(
    tmp_creds: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTGRAPH_SLACK_CLIENT_ID", "123.456")
    with (
        patch("agentgraph_connector_slack.auth.secrets.token_urlsafe", return_value="state-value"),
        patch(
            "agentgraph_connector_slack.auth._wait_for_oauth_callback",
            return_value=SlackOAuthCallback(error="access_denied", state="wrong"),
        ),
        patch("agentgraph_connector_slack.auth.webbrowser.open"),
        pytest.raises(RuntimeError, match="state did not match"),
    ):
        run_oauth_flow()


def test_oauth_flow_reports_callback_timeout(
    tmp_creds: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTGRAPH_SLACK_CLIENT_ID", "123.456")
    with (
        patch(
            "agentgraph_connector_slack.auth._wait_for_oauth_callback",
            side_effect=TimeoutError("Timed out waiting five minutes"),
        ),
        patch("agentgraph_connector_slack.auth.webbrowser.open"),
        pytest.raises(TimeoutError, match="five minutes"),
    ):
        run_oauth_flow()


def test_oauth_flow_reports_exchange_failure(
    tmp_creds: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTGRAPH_SLACK_CLIENT_ID", "123.456")
    with (
        patch("agentgraph_connector_slack.auth.secrets.token_urlsafe", return_value="state-value"),
        patch(
            "agentgraph_connector_slack.auth._wait_for_oauth_callback",
            return_value=SlackOAuthCallback(code="code", state="state-value"),
        ),
        patch("agentgraph_connector_slack.auth.webbrowser.open"),
        patch(
            "agentgraph_connector_slack.auth._exchange_oauth_code",
            side_effect=RuntimeError("Slack OAuth exchange failed: invalid_code"),
        ),
        pytest.raises(RuntimeError, match="invalid_code"),
    ):
        run_oauth_flow()


def test_oauth_flow_rejects_missing_required_scopes(
    tmp_creds: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTGRAPH_SLACK_CLIENT_ID", "123.456")
    with (
        patch("agentgraph_connector_slack.auth.secrets.token_urlsafe", return_value="state-value"),
        patch(
            "agentgraph_connector_slack.auth._wait_for_oauth_callback",
            return_value=SlackOAuthCallback(code="code", state="state-value"),
        ),
        patch("agentgraph_connector_slack.auth.webbrowser.open"),
        patch(
            "agentgraph_connector_slack.auth._exchange_oauth_code",
            return_value=_exchange_result(REQUIRED_SCOPES - {"im:history"}),
        ),
        pytest.raises(RuntimeError, match="im:history"),
    ):
        run_oauth_flow()


def test_optional_email_denial_continues_without_enrichment(
    tmp_creds: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTGRAPH_SLACK_CLIENT_ID", "123.456")
    with (
        patch("agentgraph_connector_slack.auth.secrets.token_urlsafe", return_value="state-value"),
        patch(
            "agentgraph_connector_slack.auth._wait_for_oauth_callback",
            return_value=SlackOAuthCallback(code="code", state="state-value"),
        ),
        patch("agentgraph_connector_slack.auth.webbrowser.open"),
        patch(
            "agentgraph_connector_slack.auth._exchange_oauth_code",
            return_value=_exchange_result(REQUIRED_SCOPES),
        ),
        patch("agentgraph_connector_slack.auth.httpx.get") as profile_request,
    ):
        run_oauth_flow()

    profile_request.assert_not_called()
    stored = load_platform_account("slack", "slack:T1:U1")
    assert stored is not None
    assert stored["email"] is None


def test_reauth_replaces_method_and_other_identity_remains_mixed(
    tmp_creds: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentgraph.auth.credentials import load_platform_accounts, upsert_platform_account

    upsert_platform_account(
        "slack",
        "slack:T1:U1",
        SlackBrowserCredentials(
            xoxc_token="xoxc-T1-old", d_cookie="cookie", team_id="T1", user_id="U1"
        ),
    )
    upsert_platform_account(
        "slack",
        "slack:T2:U2",
        SlackBrowserCredentials(
            xoxc_token="xoxc-T2-old", d_cookie="cookie", team_id="T2", user_id="U2"
        ),
    )
    monkeypatch.setenv("AGENTGRAPH_SLACK_CLIENT_ID", "123.456")
    with (
        patch("agentgraph_connector_slack.auth.secrets.token_urlsafe", return_value="state-value"),
        patch(
            "agentgraph_connector_slack.auth._wait_for_oauth_callback",
            return_value=SlackOAuthCallback(code="code", state="state-value"),
        ),
        patch("agentgraph_connector_slack.auth.webbrowser.open"),
        patch(
            "agentgraph_connector_slack.auth._exchange_oauth_code",
            return_value=_exchange_result(REQUIRED_SCOPES),
        ),
    ):
        run_oauth_flow(account_id="slack:T1:U1")

    accounts = {row["account_id"]: row for row in load_platform_accounts("slack")}
    assert accounts["slack:T1:U1"]["auth_method"] == "oauth"
    assert "xoxc_token" not in accounts["slack:T1:U1"]
    assert accounts["slack:T2:U2"]["auth_method"] == "browser"


def test_connector_no_args_opens_interactive_chooser() -> None:
    with patch("agentgraph_connector_slack.auth.run_interactive_auth_flow") as interactive:
        SlackConnector.run_auth_flow(account_id="slack:T1:U1", add=True)

    interactive.assert_called_once_with(account_id="slack:T1:U1", add=True)


@pytest.mark.parametrize(("choice", "selected_flow"), [("1", "oauth"), ("2", "browser")])
def test_interactive_auth_chooser_dispatches_selected_method(
    choice: str,
    selected_flow: str,
) -> None:
    with (
        patch("typer.prompt", return_value=choice),
        patch("agentgraph_connector_slack.auth.run_guided_oauth_flow") as oauth,
        patch("agentgraph_connector_slack.auth.run_cookie_flow") as browser,
    ):
        run_interactive_auth_flow(account_id="slack:T1:U1", add=True)

    selected = oauth if selected_flow == "oauth" else browser
    selected.assert_called_once_with(account_id="slack:T1:U1", add=True)
    (browser if selected_flow == "oauth" else oauth).assert_not_called()


def test_guided_oauth_uses_available_client_id_without_setup() -> None:
    with (
        patch(
            "agentgraph_connector_slack.auth._available_oauth_client_id",
            return_value="stored-client-id",
        ),
        patch("typer.confirm") as confirm,
        patch("agentgraph_connector_slack.auth.run_oauth_flow") as oauth,
    ):
        run_guided_oauth_flow(account_id="slack:T1:U1", add=True)

    confirm.assert_not_called()
    oauth.assert_called_once_with(
        account_id="slack:T1:U1",
        add=True,
        client_id="stored-client-id",
    )


def test_guided_oauth_admin_creates_app_and_enters_client_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch(
            "agentgraph_connector_slack.auth._available_oauth_client_id",
            return_value=None,
        ),
        patch("typer.confirm", return_value=True) as confirm,
        patch("typer.prompt", return_value="admin-client-id"),
        patch("agentgraph_connector_slack.auth.run_oauth_flow") as oauth,
    ):
        run_guided_oauth_flow(account_id="slack:T1:U1", add=True)

    confirm.assert_called_once_with(
        "Do you have admin permission in the Slack workspace you want to connect?",
        default=False,
    )
    oauth.assert_called_once_with(
        account_id="slack:T1:U1",
        add=True,
        client_id="admin-client-id",
    )
    output = capsys.readouterr().out
    assert "Create the AgentGraph Slack app" in output
    assert "AgentGraph Slack app manifest (JSON)" in output
    assert '"display_information": {' in output


def test_non_admin_can_enter_admin_provided_client_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch(
            "agentgraph_connector_slack.auth._available_oauth_client_id",
            return_value=None,
        ),
        patch("typer.confirm", return_value=False),
        patch("typer.prompt", side_effect=["1", "admin-client-id"]),
        patch("agentgraph_connector_slack.auth.run_oauth_flow") as oauth,
    ):
        run_guided_oauth_flow(account_id="slack:T1:U1", add=True)

    oauth.assert_called_once_with(
        account_id="slack:T1:U1",
        add=True,
        client_id="admin-client-id",
    )
    output = capsys.readouterr().out
    assert "Enter a Client ID provided by a Slack admin" in output
    assert "Set up the AgentGraph Slack App" in output


def test_non_admin_can_create_app_when_workspace_is_visible(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch(
            "agentgraph_connector_slack.auth._available_oauth_client_id",
            return_value=None,
        ),
        patch("typer.confirm", side_effect=[False, True]),
        patch("typer.prompt", side_effect=["2", "member-client-id"]),
        patch("agentgraph_connector_slack.auth.run_oauth_flow") as oauth,
    ):
        run_guided_oauth_flow(account_id="slack:T1:U1", add=True)

    oauth.assert_called_once_with(
        account_id="slack:T1:U1",
        add=True,
        client_id="member-client-id",
    )
    output = capsys.readouterr().out
    assert "At Pick a workspace" in output
    assert "Select that workspace" in output
    assert "AgentGraph Slack app manifest (JSON)" in output
    assert "Select the JSON tab" in output


def test_non_admin_missing_workspace_gets_copyable_admin_request(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch(
            "agentgraph_connector_slack.auth._available_oauth_client_id",
            return_value=None,
        ),
        patch("typer.confirm", side_effect=[False, False]),
        patch("typer.prompt", return_value="2"),
        patch("agentgraph_connector_slack.auth.run_oauth_flow") as oauth,
    ):
        run_guided_oauth_flow(account_id="slack:T1:U1", add=True)

    oauth.assert_not_called()
    output = capsys.readouterr().out
    assert "The workspace is not available in Slack's app creation list" in output
    assert "using the JSON manifest below" in output
    assert "Example request" in output
    assert "No client secret is needed" in output
    assert "https://simonexmachina.github.io/agent-graph/" in output
    assert "AgentGraph Slack app manifest (JSON)" in output
    assert '"display_information": {' in output
    assert "choose option 1" in output


def test_setup_instructions_only_include_callback_inside_manifest() -> None:
    for instructions in (
        _admin_setup_instructions(),
        _member_visible_workspace_instructions(),
        _member_missing_workspace_instructions(),
    ):
        assert instructions.count(DEFAULT_REDIRECT_URI) == 1
        assert "custom callback" not in instructions
        assert "manifest registers the callback" not in instructions


def test_oauth_client_id_sources(
    tmp_creds: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTGRAPH_SLACK_CLIENT_ID", "environment-client-id")
    assert _available_oauth_client_id(None, add=False) == "environment-client-id"

    save_platform("slack", _oauth_record())
    assert _available_oauth_client_id("slack:T1:U1", add=False) == "123.456"
    assert (
        _available_oauth_client_id("slack:T1:U1", add=True)
        == "environment-client-id"
    )


def test_authorization_instructions_cover_slack_outcomes() -> None:
    instructions = _authorization_instructions()
    assert "Allow" in instructions
    assert "Request approval" in instructions
    assert "Installation blocked" in instructions
    assert "Slackbot confirms approval" in instructions
    assert "Message for your Slack Admin" in instructions
    assert "I'd like approval to connect AgentGraph to Slack" in instructions
    assert "https://simonexmachina.github.io/agent-graph/" in instructions


@pytest.mark.asyncio
@pytest.mark.parametrize("record", [
    _oauth_record(),
    {
        "auth_method": "browser",
        "xoxc_token": "xoxc-T1-old",
        "d_cookie": "cookie",
        "team_id": "T1",
        "user_id": "U1",
    },
])
async def test_live_auth_status_supports_both_methods(
    tmp_creds: Path,
    record: dict[str, Any],
) -> None:
    save_platform("slack", record)
    with patch(
        "agentgraph_connector_slack._api_get",
        new=MagicMock(return_value=asyncio.sleep(0, result={
            "ok": True, "team": "Example", "user_id": "U1"
        })),
    ):
        status = await SlackConnector.verify_auth()

    assert status == ("ok", "Example / U1")


@pytest.mark.asyncio
@pytest.mark.parametrize("record", [_oauth_record(), {
    "xoxc_token": "xoxc-T1-old", "d_cookie": "cookie", "team_id": "T1", "user_id": "U1"
}])
async def test_invalid_credentials_are_reported_for_both_methods(
    tmp_creds: Path,
    record: dict[str, Any],
) -> None:
    save_platform("slack", record)
    with patch(
        "agentgraph_connector_slack._api_get",
        side_effect=RuntimeError("Slack API error on auth.test: invalid_auth"),
    ):
        status = await SlackConnector.verify_auth()

    assert status[0] == "invalid"
    assert "invalid_auth" in str(status[1])
