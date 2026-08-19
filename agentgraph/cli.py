"""AgentGraph CLI entry point."""

from __future__ import annotations

import asyncio
import json as _json
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import TYPE_CHECKING, cast

import typer

if TYPE_CHECKING:
    from agentgraph.connectors.base import BaseConnector

app = typer.Typer(
    name="agentgraph",
    help="Local knowledge graph for AI agents.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if not value:
        return

    try:
        current = package_version("agentgraph-server")
    except PackageNotFoundError:
        current = "unknown"
    typer.echo(f"agentgraph {current}")
    raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed version and exit.",
    ),
) -> None:
    """Configure global CLI options."""


demo_app = typer.Typer(
    help="Create reproducible local demo graphs.",
    no_args_is_help=True,
)
app.add_typer(demo_app, name="demo")
auth_app = typer.Typer(
    help="Show auth provider state or manage connector authentication.",
    invoke_without_command=True,
    no_args_is_help=False,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
app.add_typer(auth_app, name="auth")


@contextmanager
def _readable_credentials() -> Iterator[None]:
    """Report a damaged credentials file as an error instead of a traceback."""
    from agentgraph.auth.credentials import CredentialsFileError

    try:
        yield
    except CredentialsFileError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def _status_label(status: str) -> str:
    return {"ok": "authenticated", "missing": "not authenticated", "invalid": "INVALID"}.get(
        status, status
    )


def _server_is_running() -> bool:
    """Return whether the configured AgentGraph server responds to health checks."""
    from agentgraph.config import get_settings

    settings = get_settings()
    host = "127.0.0.1" if settings.server_host in ("", "0.0.0.0", "::") else settings.server_host
    url = f"http://{host}:{settings.server_port}/health"
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


@demo_app.command("add")
def add_demo_command(
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Add the fictional Atlas graph to the configured database."""
    from agentgraph.config import get_config_paths
    from agentgraph.demo import add_demo

    try:
        result = asyncio.run(add_demo(get_config_paths()[0]))
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if json:
        typer.echo(_json.dumps(result, indent=2))
        return
    typer.echo(f"Added Atlas demo fixtures to {result['database']}")
    typer.echo(
        f"{result['entities']} entities, {result['persons']} people, {result['edges']} edges"
    )


@demo_app.command("remove")
def remove_demo_command(
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Remove Atlas demo fixtures from the configured database."""
    from agentgraph.config import get_config_paths
    from agentgraph.demo import remove_demo

    result = asyncio.run(remove_demo(get_config_paths()[0]))
    if json:
        typer.echo(_json.dumps(result, indent=2))
        return
    typer.echo(f"Removed {result['removed']} Atlas demo entities from {result['database']}")


def _remove_auth_credentials(provider: str, account_id: str | None) -> dict[str, object]:
    from agentgraph.auth.credentials import remove_platform, remove_platform_account

    removed = (
        remove_platform_account(provider, account_id)
        if account_id is not None
        else remove_platform(provider)
    )
    result: dict[str, object] = {
        "provider": provider,
        "removed": removed,
    }
    if account_id is not None:
        result["account_id"] = account_id
    return result


def _parse_auth_args(
    args: list[str],
    *,
    account: str | None,
    json: bool,
    verify: bool,
    add: bool,
    provider_args: list[str] | None = None,
) -> tuple[list[str], str | None, bool, bool, bool, list[str], str | None]:
    positionals: list[str] = []
    parsed_account = account
    parsed_json = json
    parsed_verify = verify
    parsed_add = add
    parsed_provider_args = list(provider_args or [])
    error: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--json":
            parsed_json = True
        elif arg == "--verify":
            parsed_verify = True
        elif arg == "--add":
            parsed_add = True
        elif arg == "--account":
            if i + 1 >= len(args):
                error = "--account requires an account ID"
                break
            parsed_account = args[i + 1]
            i += 1
        elif arg.startswith("--account="):
            parsed_account = arg.split("=", 1)[1]
        elif arg.startswith("-"):
            if not positionals or positionals[0] in ("status", "remove"):
                error = f"Unknown option for auth: {arg}"
                break
            parsed_provider_args.append(arg)
        else:
            if len(positionals) == 1 and positionals[0] not in ("status", "remove"):
                parsed_provider_args.append(arg)
            else:
                positionals.append(arg)
        i += 1
    return (
        positionals,
        parsed_account,
        parsed_json,
        parsed_verify,
        parsed_add,
        parsed_provider_args,
        error,
    )


@auth_app.callback()
def auth(
    auth_args: list[str] | None = typer.Argument(
        None,
        help="Use 'status', 'remove <provider>', or an auth provider such as google, slack, or discord",
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
    verify: bool = typer.Option(
        False, "--verify", help="Live-check credentials with provider APIs"
    ),
    add: bool = typer.Option(
        False, "--add", help="Add another authenticated account for this provider"
    ),
    account: str | None = typer.Option(
        None, "--account", help="Re-authenticate a specific account ID"
    ),
) -> None:
    """Show auth status or authenticate a provider."""
    (
        args,
        parsed_account,
        parsed_json,
        parsed_verify,
        parsed_add,
        parsed_provider_args,
        parse_error,
    ) = _parse_auth_args(
        auth_args or [],
        account=account,
        json=json,
        verify=verify,
        add=add,
    )
    if parse_error is not None:
        typer.echo(parse_error, err=True)
        raise typer.Exit(code=1)

    target = args[0] if args else None
    if target == "remove":
        if len(args) > 2:
            typer.echo(f"Unexpected argument for auth remove: {args[2]}", err=True)
            raise typer.Exit(code=1)
        if len(args) < 2:
            typer.echo(
                "Usage: agentgraph auth remove <provider> [--account <account-id>] [--json]",
                err=True,
            )
            raise typer.Exit(code=1)
        provider = args[1]
        with _readable_credentials():
            result = _remove_auth_credentials(provider, parsed_account)

        if parsed_json:
            typer.echo(_json.dumps(result, indent=2))
            return

        if result["removed"]:
            if parsed_account is None:
                typer.echo(f"Removed stored credentials for {provider}.")
            else:
                typer.echo(f"Removed stored credentials for {provider} account {parsed_account}.")
            return

        if parsed_account is None:
            typer.echo(f"No stored credentials found for {provider}.", err=True)
        else:
            typer.echo(
                f"No stored credentials found for {provider} account {parsed_account}.",
                err=True,
            )
        raise typer.Exit(code=1)

    if len(args) > 1:
        typer.echo(f"Unexpected argument for auth: {args[1]}", err=True)
        raise typer.Exit(code=1)

    if target not in (None, "status"):
        from agentgraph.connectors.registry import bootstrap, get_all_connectors
        from agentgraph.connectors.status import (
            auth_provider_connectors,
            run_auth_provider_flow,
        )

        bootstrap()
        all_connectors = get_all_connectors()
        grouped = auth_provider_connectors(all_connectors)
        seen = {label: connectors[0] for label, connectors in grouped.items()}

        if target not in seen:
            available = ", ".join(["status", *sorted(seen)])
            typer.echo(f"Unknown auth target '{target}'. Available: {available}", err=True)
            raise typer.Exit(code=1)

        with _readable_credentials():
            try:
                run_auth_provider_flow(
                    all_connectors,
                    target,
                    account_id=parsed_account,
                    add=parsed_add,
                    args=parsed_provider_args,
                )
            except ValueError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(code=2) from exc
        return

    from agentgraph.connectors.registry import bootstrap, get_all_connectors
    from agentgraph.connectors.status import auth_provider_status_items

    bootstrap()
    with _readable_credentials():
        items = asyncio.run(auth_provider_status_items(get_all_connectors(), verify=parsed_verify))

    if parsed_json:
        typer.echo(_json.dumps(items, indent=2))
        return

    for item in items:
        status = str(item["auth_status"])
        detail = item["auth_detail"]
        auth_state = _status_label(status)
        if detail:
            auth_state = (
                f"{auth_state} ({detail})" if status != "ok" else f"{auth_state} as {detail}"
            )
        connectors = ", ".join(str(source) for source in cast(list[object], item["connectors"]))
        typer.echo(f"  {item['provider']:<12}  {item['description']}")
        typer.echo(f"  {'':<12}  auth: {auth_state}  |  connectors: {connectors}")
        accounts = cast(list[dict[str, object]], item.get("accounts") or [])
        for account_row in accounts:
            account_status = str(account_row["auth_status"])
            account_auth = _status_label(account_status)
            account_detail = account_row.get("auth_detail")
            if account_detail:
                account_auth = (
                    f"{account_auth} ({account_detail})"
                    if account_status != "ok"
                    else f"{account_auth} as {account_detail}"
                )
            typer.echo(
                f"  {'':<12}  account: {account_row['label']} [{account_row['account_id']}]"
                f"  |  method: {account_row.get('auth_method') or 'unknown'}  |  {account_auth}"
            )


@app.command(
    "connector",
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
        "help_option_names": [],
    },
)
def connector_command(
    ctx: typer.Context,
    source: str | None = typer.Argument(None, help="Connector source, e.g. rss"),
    args: list[str] | None = typer.Argument(None, help="Connector-owned command and arguments"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
    help: bool = typer.Option(False, "--help", help="Show this message and exit."),
) -> None:
    """Run a connector-owned command."""
    from agentgraph.connectors.registry import bootstrap, get_connector

    if source is None:
        from typer.rich_utils import rich_format_help

        rich_format_help(obj=ctx.command, ctx=ctx, markup_mode="rich")
        return

    bootstrap()
    connector = get_connector(source)
    if connector is None:
        typer.echo(f"Unknown connector '{source}'", err=True)
        raise typer.Exit(code=1)

    if help:
        typer.echo(type(connector).cli_help())
        return

    command_args = args or []
    try:
        result = type(connector).run_cli_command(command_args)
        effects = type(connector).command_effects(command_args, result)
        if effects.delete_entities:
            from agentgraph.cli_query import run_graph_operation
            from agentgraph.connectors.command_effects import execute_deletions

            result["deleted_entities"] = run_graph_operation(lambda: execute_deletions(effects))
        if effects.poll:
            from agentgraph.cli_sync import queue_connector_poll

            result["poll"] = queue_connector_poll(connector.source)
        if effects.ingest:
            from agentgraph.cli_sync import queue_connector_ingest

            result["ingest"] = queue_connector_ingest(
                connector.source,
                account_id=effects.ingest_account_id,
            )
    except NotImplementedError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if json:
        typer.echo(_json.dumps(result, indent=2))
        return
    typer.echo(type(connector).format_cli_result(result))


@app.command()
def connectors(
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
    verify: bool = typer.Option(
        False, "--verify", help="Live-check connector credentials with provider APIs"
    ),
) -> None:
    """List installed connectors and their sync status."""
    from agentgraph.connectors.registry import bootstrap, get_all_connectors
    from agentgraph.connectors.status import connector_status_items
    from agentgraph.core.runtime import backend_context

    bootstrap()
    all_connectors = get_all_connectors()

    async def _gather() -> list[dict[str, object]]:
        async with backend_context() as backend:
            return await connector_status_items(all_connectors, backend, verify=verify)

    items = asyncio.run(_gather())

    if json:
        typer.echo(_json.dumps(items, indent=2))
        return

    for item in items:
        sync = str(item["sync"])
        last_sync = str(item["last_sync"])
        desc = item["description"] or item["source"]
        typer.echo(f"  {item['source']:<12}  {desc}")
        status = item["auth_status"]
        if status is None:
            typer.echo(f"  {'':<12}  sync: {sync}  |  last sync: {last_sync}")
            continue
        status_label = str(status)
        detail = item["auth_detail"]
        auth = _status_label(status_label)
        if detail:
            auth = f"{auth} ({detail})" if status_label != "ok" else f"{auth} as {detail}"
        typer.echo(
            f"  {'':<12}  auth: {auth} via {item['auth_provider']}  |  sync: {sync}  |  last sync: {last_sync}"
        )


@app.command()
def serve(
    reload: bool = typer.Option(False, "--reload", "-r", help="Auto-reload on code changes"),
) -> None:
    """Start the AgentGraph backend server."""
    import uvicorn

    from agentgraph.config import get_config_paths, get_settings
    from agentgraph.logging import configure_logging

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_file)
    typer.echo(f"AgentGraph config directory: {get_config_paths()[0]}")
    typer.echo(f"AgentGraph log file: {settings.log_file.expanduser()}")
    uvicorn.run(
        "agentgraph.server.app:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=reload,
    )


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    type: list[str] = typer.Option([], "--type", "-t", help="Filter by entity type"),
    platform: str | None = typer.Option(
        None, "--platform", "-p", help="Scope to a single platform (e.g. slack, discord)"
    ),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum results"),
    min_score: float = typer.Option(0.03, "--min-score", help="Minimum relevance score (0–1)"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Search the knowledge graph."""
    from agentgraph.cli_query import cmd_search

    cmd_search(
        query=query,
        entity_types=type,
        platform=platform,
        limit=limit,
        min_score=min_score,
        as_json=json,
    )


@app.command()
def get(
    entity_id: str = typer.Argument(..., help="Entity ID, platform ref, or URL"),
    resolve: bool = typer.Option(
        False, "--resolve", "-r", help="Fetch from source if entity is a stub (no content)"
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Fetch full details for an existing entity."""
    from agentgraph.cli_query import cmd_get

    cmd_get(entity_id=entity_id, as_json=json, resolve=resolve)


@app.command()
def edges(
    entity_id: str = typer.Argument(..., help="Entity ID"),
    type: str = typer.Option("", "--type", "-t", help="Filter by edge type"),
    direction: str = typer.Option("both", "--direction", "-d", help="in | out | both"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List edges for an entity."""
    from agentgraph.cli_query import cmd_edges

    cmd_edges(entity_id=entity_id, edge_type=type or None, direction=direction, as_json=json)


@app.command()
def traverse(
    entity_id: str = typer.Argument(..., help="Start entity ID"),
    depth: int = typer.Option(2, "--depth", "-d", help="Maximum traversal depth"),
    resolve: bool = typer.Option(
        False, "--resolve", "-r", help="Fetch stub nodes from source before returning"
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Traverse the graph from an entity."""
    from agentgraph.cli_query import cmd_traverse

    cmd_traverse(entity_id=entity_id, max_depth=depth, as_json=json, resolve=resolve)


@app.command()
def fetch(
    platform: str = typer.Argument(..., help="Platform name (e.g. gdocs, slack, discord, rss)"),
    resource_id: str = typer.Argument(..., help="Platform-specific entity ID"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Trigger a connector fetch for a platform entity."""
    from agentgraph.cli_query import cmd_fetch

    cmd_fetch(platform=platform, resource_id=resource_id, as_json=json)


@app.command("fetch-entity")
def fetch_entity_cmd(
    entity_id: str = typer.Argument(..., help="Internal entity UUID"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Trigger a connector re-fetch for an entity by its internal ID."""
    from agentgraph.cli_query import cmd_fetch_entity

    cmd_fetch_entity(entity_id=entity_id, as_json=json)


@app.command()
def download(
    entity_id: str = typer.Argument(..., help="Entity ID, UUID prefix, or platform ref"),
    output: str | None = typer.Option(None, "--output", "-o", help="Output file path or directory"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Download an entity's source file using connector auth."""
    from agentgraph.cli_query import cmd_download

    cmd_download(entity_id=entity_id, output_path=output, as_json=json)


@app.command()
def bookmark(
    target: str = typer.Argument(..., help="Entity ID, UUID prefix, platform ref, or URL"),
    remove: bool = typer.Option(
        False, "--remove", help="Remove bookmark protection instead of adding it"
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Set or remove bookmark protection for an entity or URL."""
    from agentgraph.cli_query import cmd_bookmark

    cmd_bookmark(target=target, bookmarked=not remove, as_json=json)


@app.command("delete")
def delete_cmd(
    target: str = typer.Argument(..., help="Entity ID, UUID prefix, platform ref, or URL"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Delete an entity from the graph."""
    from agentgraph.cli_query import cmd_delete

    cmd_delete(target=target, as_json=json)


@app.command("unify-persons")
def unify_persons_cmd(
    primary_entity_id: str = typer.Argument(..., help="Person entity to keep"),
    duplicate_entity_ids: list[str] = typer.Argument(
        ..., help="Duplicate Person entities to merge into the primary"
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Merge duplicate Person entities that refer to the same human."""
    from agentgraph.cli_query import cmd_unify_persons

    cmd_unify_persons(
        primary_entity_id=primary_entity_id,
        duplicate_entity_ids=duplicate_entity_ids,
        as_json=json,
    )


@app.command()
def onboard() -> None:
    """Interactive setup: authenticate with each installed connector."""
    from agentgraph.connectors.registry import bootstrap, get_all_connectors

    bootstrap()
    # Dedup by auth_label so multi-connector platforms (e.g. Google) appear once.
    seen: dict[str, BaseConnector] = {}
    for connector in get_all_connectors():
        label: str = getattr(connector, "auth_label", None) or connector.source
        if label not in seen:
            seen[label] = connector

    # Only connectors with an explicit onboarding prompt own an interactive setup flow.
    # Generic connectors such as Web are configured through connector commands instead.
    steps = [
        (label, connector)
        for label, connector in seen.items()
        if getattr(connector, "onboard_prompt", None)
    ]
    steps.sort(key=lambda item: getattr(item[1], "onboard_last", False))
    total = len(steps) + 1

    typer.echo("=== AgentGraph Setup ===\n")

    for i, (label, connector) in enumerate(steps, 1):
        prompt: str = getattr(connector, "onboard_prompt", None) or f"Set up {label}?"
        description: str = getattr(connector, "auth_description", None) or label.title()
        typer.echo(f"Step {i}/{total}: {description}")
        if typer.confirm(f"  {prompt}", default=True):
            type(connector).run_auth_flow()
        else:
            typer.echo("  Skipped.")
        if i < total:
            typer.echo()

    typer.echo(f"\nStep {total}/{total}: Install the AgentGraph Chrome Extension")
    typer.echo(
        "https://chromewebstore.google.com/detail/agentgraph-extension/iilkfclglabllelhjacijldknapbhidi"
    )
    if not _server_is_running():
        typer.echo("Run `agentgraph serve` to start the server.")


@app.command()
def mcp_config() -> None:
    """Print MCP client setup instructions."""
    import json
    import sys

    binary = sys.argv[0]

    config = {
        "mcpServers": {
            "agentgraph": {
                "command": binary,
                "args": ["mcp-serve"],
            }
        }
    }

    typer.echo("\nFor stdio MCP clients, add this to your MCP client config:\n")
    typer.echo("  Claude Desktop:  ~/Library/Application Support/Claude/claude_desktop_config.json")
    typer.echo("  Claude Code:     ~/.claude/mcp.json  (or .claude/mcp.json in your project)\n")
    typer.echo(json.dumps(config, indent=2))
    typer.echo()
    typer.echo("For ChatGPT developer mode, do not use the stdio JSON above.")
    typer.echo("Run a streamable HTTP MCP server:")
    typer.echo(f"  {binary} mcp-serve --transport streamable-http --port 8808")
    typer.echo("Local endpoint:")
    typer.echo("  http://127.0.0.1:8808/mcp")
    typer.echo("ChatGPT requires a reachable HTTPS URL. Use Secure MCP Tunnel, ngrok,")
    typer.echo("or Cloudflare Tunnel, then create an app/connector in ChatGPT Developer mode")
    typer.echo("with the public URL ending in /mcp, for example:")
    typer.echo("  https://your-tunnel.example/mcp")
    typer.echo()
    typer.echo("SSE is also supported by the server if your MCP client needs it:")
    typer.echo(f"  {binary} mcp-serve --transport sse --port 8808")
    typer.echo("  http://127.0.0.1:8808/sse")
    typer.echo()


@app.command()
def install_skill(
    skill: str = typer.Argument("AgentGraph", help="Bundled skill to install"),
    target: str = typer.Option(
        "user",
        "--target",
        help="Install target: user (~/.agents/skills) or project (./.agents/skills)",
    ),
    claude: bool = typer.Option(
        True,
        "--claude/--no-claude",
        help="Link into Claude by default; --no-claude skips ~/.claude/skills or ./.claude/skills",
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing installed skill"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Install a bundled AgentGraph skill into an agent skill directory."""
    from agentgraph.skills import SkillInstallError
    from agentgraph.skills import install_skill as install_agentgraph_skill

    if target not in ("user", "project"):
        typer.echo("Target must be 'user' or 'project'", err=True)
        raise typer.Exit(code=1)

    try:
        result = install_agentgraph_skill(skill, target=target, force=force, claude=claude)
    except SkillInstallError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if json:
        typer.echo(_json.dumps(result.to_dict(), indent=2))
        return

    typer.echo(f"Installed AgentGraph skill '{result.skill}' to {result.destination}")
    if result.claude_destination is not None:
        typer.echo(f"Linked Claude skill to {result.claude_destination}")


@app.command()
def mcp_serve(
    transport: str = typer.Option(
        "stdio", "--transport", help="Transport: stdio, sse, or streamable-http"
    ),
    port: int = typer.Option(8808, "--port", help="Port for sse / streamable-http transports"),
    host: str = typer.Option(
        "127.0.0.1", "--host", help="Host to bind for sse / streamable-http transports"
    ),
) -> None:
    """Start the AgentGraph MCP server."""
    import asyncio

    from agentgraph.core.context import set_backend
    from agentgraph.core.runtime import create_backend

    backend = create_backend()
    asyncio.run(backend.initialize())
    set_backend(backend)

    from agentgraph.mcp.server import mcp

    if transport in ("sse", "streamable-http"):
        mcp.settings.port = port
        mcp.settings.host = host
        # Clear DNS rebinding protection when binding to a non-localhost address
        # (the singleton is initialized with host=127.0.0.1 which enables it by default)
        if host not in ("127.0.0.1", "localhost", "::1"):
            mcp.settings.transport_security = None
    mcp.run(transport=transport)  # type: ignore[arg-type]


@app.command()
def poll(
    source: str | None = typer.Argument(
        None, help="Connector source to poll (e.g. slack, gmail, rss). Omit to poll all."
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Trigger a background poll for one or all connectors."""
    from agentgraph.cli_sync import cmd_poll

    cmd_poll(source=source, as_json=json)


@app.command()
def query(
    entity_type: str = typer.Option(..., "--type", "-t", help="Entity type to query"),
    filter: list[str] = typer.Option(
        [], "--filter", "-f", help="key=value filters (column or metadata)"
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        "-s",
        help="Only results after this time: ISO timestamp or relative (12h, 30m, 2d)",
    ),
    mine: bool = typer.Option(False, "--mine", "-m", help="Only entities authored by me"),
    has_attachments: bool = typer.Option(
        False, "--has-attachments", help="Only Message entities that have file/image attachments"
    ),
    limit: int = typer.Option(50, "--limit", "-n", help="Maximum results"),
    order_by: str = typer.Option(
        "created_at",
        "--order-by",
        "-o",
        help=(
            "Column to sort by (created_at, updated_at, source_created_at, "
            "source_updated_at, observed_at, synced_at)"
        ),
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Query entities by type and filters."""
    from agentgraph.cli_query import cmd_query

    parsed_filters = dict(f.split("=", 1) for f in filter if "=" in f)
    cmd_query(
        entity_type=entity_type,
        filters=parsed_filters,
        limit=limit,
        order_by=order_by,
        since=since,
        authored_by_me=mine,
        has_attachments=has_attachments,
        as_json=json,
    )
