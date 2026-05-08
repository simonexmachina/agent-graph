"""Tests for CLI structure."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from agentgraph.cli import app

runner = CliRunner()


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "serve" in result.output
    assert "search" in result.output
    assert "auth" in result.output


def test_auth_help() -> None:
    result = runner.invoke(app, ["auth", "--help"])
    assert result.exit_code == 0
    assert "platform" in result.output.lower()


class _FakeConnector:
    source = "slack"
    auth_label = "slack"
    auth_description = "Slack"
    onboard_prompt = "Set up Slack?"
    auth_called = False

    @classmethod
    def run_auth_flow(cls) -> None:
        cls.auth_called = True

    @classmethod
    def get_authenticated_user(cls) -> None:
        return None


def test_auth_unknown_platform_exits_nonzero() -> None:
    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.connectors.registry.get_all_connectors", return_value=[_FakeConnector()]):
        result = runner.invoke(app, ["auth", "notaplatform"])
    assert result.exit_code != 0
    assert "notaplatform" in result.output


def test_auth_dispatches_to_connector() -> None:
    _FakeConnector.auth_called = False
    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.connectors.registry.get_all_connectors", return_value=[_FakeConnector()]):
        result = runner.invoke(app, ["auth", "slack"])
    assert result.exit_code == 0
    assert _FakeConnector.auth_called


def test_search_requires_query() -> None:
    result = runner.invoke(app, ["search"])
    assert result.exit_code != 0
