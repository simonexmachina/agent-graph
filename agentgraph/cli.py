"""AgentGraph CLI entry point."""

from __future__ import annotations

import asyncio
import json as _json
from typing import cast

import typer

from agentgraph.connectors.base import BaseConnector

app = typer.Typer(
    name="agentgraph",
    help="Local knowledge graph for AI agents.",
    no_args_is_help=True,
)
auth_app = typer.Typer(
    help="Show auth provider state or manage connector authentication.",
    invoke_without_command=True,
    no_args_is_help=False,
)
app.add_typer(auth_app, name="auth")


def _run_auth_flow(connector_cls: type[BaseConnector], account_id: str | None, add: bool) -> None:
    try:
        connector_cls.run_auth_flow(account_id=account_id, add=add)
    except TypeError:
        connector_cls.run_auth_flow()


def _status_label(status: str) -> str:
    return {"ok": "authenticated", "missing": "not authenticated", "invalid": "INVALID"}.get(status, status)


@auth_app.callback()
def auth(
    target: str | None = typer.Argument(None, help="Use 'status' or an auth provider such as google, slack, discord, or rss"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
    add: bool = typer.Option(False, "--add", help="Add another authenticated account for this provider"),
    account: str | None = typer.Option(None, "--account", help="Re-authenticate a specific account ID"),
    xoxc_token: str | None = typer.Option(None, "--xoxc-token", help="Slack xoxc- token (skips interactive prompt)"),
    d_cookie: str | None = typer.Option(None, "--d-cookie", help="Slack d cookie value (skips interactive prompt)"),
) -> None:
    """Show auth status or authenticate a provider."""
    if target not in (None, "status"):
        from agentgraph.connectors.registry import bootstrap, get_all_connectors
        from agentgraph.connectors.status import auth_provider_connectors

        bootstrap()
        grouped = auth_provider_connectors(get_all_connectors())
        seen = {label: connectors[0] for label, connectors in grouped.items()}

        if target not in seen:
            available = ", ".join(["status", *sorted(seen)])
            typer.echo(f"Unknown auth target '{target}'. Available: {available}", err=True)
            raise typer.Exit(code=1)

        if target == "slack" and (xoxc_token is not None or d_cookie is not None):
            from agentgraph_connector_slack.auth import (
                run_cookie_flow,  # type: ignore[import-not-found]
            )
            run_cookie_flow(account_id=account, add=add, xoxc_token=xoxc_token, d_cookie=d_cookie)
            return

        _run_auth_flow(type(seen[target]), account, add)
        return

    from agentgraph.connectors.registry import bootstrap, get_all_connectors
    from agentgraph.connectors.status import auth_provider_status_items

    bootstrap()
    items = asyncio.run(auth_provider_status_items(get_all_connectors()))

    if json:
        typer.echo(_json.dumps(items, indent=2))
        return

    for item in items:
        status = str(item["auth_status"])
        detail = item["auth_detail"]
        auth_state = _status_label(status)
        if detail:
            auth_state = (
                f"{auth_state} ({detail})"
                if status != "ok"
                else f"{auth_state} as {detail}"
            )
        connectors = ", ".join(
            str(source) for source in cast(list[object], item["connectors"])
        )
        typer.echo(f"  {item['provider']:<12}  {item['description']}")
        typer.echo(f"  {'':<12}  auth: {auth_state}  |  connectors: {connectors}")
        accounts = cast(list[dict[str, object]], item.get("accounts") or [])
        for account in accounts:
            account_status = str(account["auth_status"])
            account_auth = _status_label(account_status)
            account_detail = account.get("auth_detail")
            if account_detail:
                account_auth = (
                    f"{account_auth} ({account_detail})"
                    if account_status != "ok"
                    else f"{account_auth} as {account_detail}"
                )
            typer.echo(f"  {'':<12}  account: {account['label']} [{account['account_id']}]  |  {account_auth}")


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

    try:
        result = type(connector).run_cli_command(args or [])
    except NotImplementedError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if json:
        typer.echo(_json.dumps(result, indent=2))
        return
    typer.echo(_json.dumps(result, indent=2))


@app.command()
def connectors(
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List installed connectors and their auth status."""
    from agentgraph.connectors.registry import bootstrap, get_all_connectors
    from agentgraph.connectors.status import connector_status_items
    from agentgraph.core.runtime import backend_context

    bootstrap()
    all_connectors = get_all_connectors()

    async def _gather() -> list[dict[str, object]]:
        async with backend_context() as backend:
            return await connector_status_items(all_connectors, backend)

    items = asyncio.run(_gather())

    if json:
        typer.echo(_json.dumps(items, indent=2))
        return

    for item in items:
        sync = str(item["sync"])
        last_sync = str(item["last_sync"])
        desc = item["description"] or item["source"]
        status = str(item["auth_status"])
        detail = item["auth_detail"]
        auth = _status_label(status)
        if detail:
            auth = f"{auth} ({detail})" if status != "ok" else f"{auth} as {detail}"
        typer.echo(f"  {item['source']:<12}  {desc}")
        typer.echo(
            f"  {'':<12}  auth: {auth} via {item['auth_provider']}  |  sync: {sync}  |  last sync: {last_sync}"
        )


@app.command()
def serve(
    reload: bool = typer.Option(False, "--reload", "-r", help="Auto-reload on code changes"),
) -> None:
    """Start the AgentGraph backend server."""
    import uvicorn

    from agentgraph.config import get_settings
    from agentgraph.logging import configure_logging

    settings = get_settings()
    configure_logging(settings.log_level)
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
    platform: str | None = typer.Option(None, "--platform", "-p", help="Scope to a single platform (e.g. slack, discord)"),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum results"),
    min_score: float = typer.Option(0.03, "--min-score", help="Minimum relevance score (0–1)"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Search the knowledge graph."""
    from agentgraph.cli_query import cmd_search

    cmd_search(query=query, entity_types=type, platform=platform, limit=limit, min_score=min_score, as_json=json)


@app.command()
def get(
    entity_id: str = typer.Argument(..., help="Entity ID"),
    resolve: bool = typer.Option(False, "--resolve", "-r", help="Fetch from source if entity is a stub (no content)"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Fetch full details for an entity."""
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
    resolve: bool = typer.Option(False, "--resolve", "-r", help="Fetch stub nodes from source before returning"),
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


@app.command("unify-persons")
def unify_persons_cmd(
    primary_entity_id: str = typer.Argument(..., help="Person entity to keep"),
    duplicate_entity_ids: list[str] = typer.Argument(..., help="Duplicate Person entities to merge into the primary"),
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

    steps = list(seen.items())
    total = len(steps)

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

    typer.echo("\nSetup complete. Run `agentgraph serve` to start the server.")


@app.command()
def mcp_config() -> None:
    """Print the MCP server config snippet for Claude Desktop / Claude Code / ChatGPT."""
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

    typer.echo("\nAdd this to your MCP client config:\n")
    typer.echo("  Claude Desktop:  ~/Library/Application Support/Claude/claude_desktop_config.json")
    typer.echo("  Claude Code:     ~/.claude/mcp.json  (or .claude/mcp.json in your project)\n")
    typer.echo("  ChatGPT:         Settings → Apps & Connectors → Advanced settings → Developer mode")
    typer.echo("                   Add a remote MCP connector using SSE or streaming HTTP.\n")
    typer.echo(json.dumps(config, indent=2))
    typer.echo()
    typer.echo("For SSE / streamable-http transport instead of stdio:")
    typer.echo(f"  {binary} mcp-serve --transport sse --port 8808")
    typer.echo(f"  {binary} mcp-serve --transport streamable-http --port 8808")
    typer.echo("  Then point ChatGPT at the remote MCP endpoint instead of using the stdio snippet above.")
    typer.echo()


@app.command()
def mcp_serve(
    transport: str = typer.Option("stdio", "--transport", help="Transport: stdio, sse, or streamable-http"),
    port: int = typer.Option(8808, "--port", help="Port for sse / streamable-http transports"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind for sse / streamable-http transports"),
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
    source: str | None = typer.Argument(None, help="Connector source to poll (e.g. slack, gmail, rss). Omit to poll all."),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Trigger a background poll for one or all connectors."""
    from agentgraph.cli_query import cmd_poll

    cmd_poll(source=source, as_json=json)


@app.command()
def ingest(
    source: str = typer.Argument(..., help="Connector source to ingest (e.g. gmail, rss)"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Run a one-shot bulk ingest for a connector (all data within the retention window)."""
    from agentgraph.cli_query import cmd_ingest

    cmd_ingest(source=source, as_json=json)


@app.command()
def query(
    entity_type: str = typer.Option(..., "--type", "-t", help="Entity type to query"),
    filter: list[str] = typer.Option([], "--filter", "-f", help="key=value filters (column or metadata)"),
    since: str | None = typer.Option(None, "--since", "-s", help="Only results after this time: ISO timestamp or relative (12h, 30m, 2d)"),
    mine: bool = typer.Option(False, "--mine", "-m", help="Only entities authored by me"),
    has_attachments: bool = typer.Option(False, "--has-attachments", help="Only Message entities that have file/image attachments"),
    limit: int = typer.Option(50, "--limit", "-n", help="Maximum results"),
    order_by: str = typer.Option("created_at", "--order-by", "-o", help="Column to sort by (created_at, updated_at, last_accessed)"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Query entities by type and filters."""
    from agentgraph.cli_query import cmd_query

    parsed_filters = dict(f.split("=", 1) for f in filter if "=" in f)
    cmd_query(entity_type=entity_type, filters=parsed_filters, limit=limit, order_by=order_by, since=since, authored_by_me=mine, has_attachments=has_attachments, as_json=json)
