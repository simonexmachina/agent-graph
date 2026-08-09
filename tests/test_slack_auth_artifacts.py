"""Contracts for Slack auth documentation, skill, and app manifest."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, cast

import yaml
from agentgraph_connector_slack.auth import (
    DEFAULT_REDIRECT_URI,
    OPTIONAL_SCOPES,
    REQUIRED_SCOPES,
)

ROOT = Path(__file__).resolve().parent.parent
SLACK_PACKAGE = ROOT / "packages" / "agentgraph-connector-slack"
MANIFEST_PATH = SLACK_PACKAGE / "agentgraph_connector_slack" / "slack-app-manifest.yaml"


def test_slack_manifest_enables_pkce_rotation_and_scopes() -> None:
    raw = yaml.safe_load(MANIFEST_PATH.read_text())
    manifest = cast(dict[str, Any], raw)
    oauth = cast(dict[str, Any], manifest["oauth_config"])
    scope_config = cast(dict[str, list[str]], oauth["scopes"])
    settings = cast(dict[str, Any], manifest["settings"])

    assert oauth["pkce_enabled"] is True
    assert oauth["token_management_enabled"] is True
    assert settings["token_rotation_enabled"] is True
    assert oauth["redirect_urls"] == [DEFAULT_REDIRECT_URI]
    assert set(scope_config["user"]) == REQUIRED_SCOPES | OPTIONAL_SCOPES
    assert set(scope_config["user_optional"]) == OPTIONAL_SCOPES


def test_slack_manifest_is_in_package_data() -> None:
    config = tomllib.loads((SLACK_PACKAGE / "pyproject.toml").read_text())
    assert config["tool"]["setuptools"]["package-data"]["agentgraph_connector_slack"] == [
        "slack-app-manifest.yaml"
    ]


def test_slack_auth_skill_documents_oauth_and_explicit_fallback() -> None:
    skill = (ROOT / ".agents" / "skills" / "slack-auth" / "SKILL.md").read_text()
    assert "agentgraph auth slack" in skill
    assert "AGENTGRAPH_SLACK_CLIENT_ID" in skill
    assert "--method browser" in skill
    assert "users:read.email" in skill
    assert "agentgraph auth remove slack" in skill


def test_graph_skill_has_cli_and_mcp_auth_parity() -> None:
    skill = (ROOT / ".agents" / "skills" / "graph" / "SKILL.md").read_text()
    assert "agentgraph auth slack [--method oauth|browser]" in skill
    assert "authenticate_provider_tool(provider, args, account_id, add)" in skill
    assert "auth_method" in skill


def test_slack_docs_cover_admin_approval_configuration_and_revocation() -> None:
    guide = (ROOT / "docs-src" / "slack.md").read_text()
    for required in (
        "workspace admin",
        "approve",
        "AGENTGRAPH_SLACK_CLIENT_ID",
        "AGENTGRAPH_SLACK_REDIRECT_URI",
        DEFAULT_REDIRECT_URI,
        "Revoke access",
        "Browser-session fallback",
        "users:read.email",
    ):
        assert required in guide


def test_mcp_authentication_operation_is_documented() -> None:
    reference = (ROOT / "docs-src" / "mcp" / "authenticate-provider.md").read_text()
    index = (ROOT / "docs-src" / "mcp" / "index.md").read_text()
    assert "authenticate_provider_tool(provider" in reference
    assert "authenticate_provider_tool" in index
