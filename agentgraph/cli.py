"""AgentGraph CLI entry point."""

from __future__ import annotations

import typer

app = typer.Typer(
    name="agentgraph",
    help="Local knowledge graph for AI agents.",
    no_args_is_help=True,
)

auth_app = typer.Typer(help="Manage source credentials.")
app.add_typer(auth_app, name="auth")


@auth_app.command("google-docs")
def auth_google_docs() -> None:
    """Authenticate with Google Docs via OAuth2 browser flow."""
    from agentgraph.auth.google import run_oauth_flow

    run_oauth_flow()


@auth_app.command("slack")
def auth_slack() -> None:
    """Store Slack cookie credentials (xoxc- token + d cookie)."""
    from agentgraph.auth.slack import run_cookie_flow

    run_cookie_flow()


@auth_app.command("discord")
def auth_discord() -> None:
    """Store Discord bot token credentials."""
    from agentgraph.auth.discord import run_token_flow

    run_token_flow()


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
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum results"),
    min_score: float = typer.Option(0.03, "--min-score", help="Minimum relevance score (0–1)"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Search the knowledge graph."""
    from agentgraph.cli_query import cmd_search

    cmd_search(query=query, entity_types=type, limit=limit, min_score=min_score, as_json=json)


@app.command()
def get(
    entity_id: str = typer.Argument(..., help="Entity ID"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Fetch full details for an entity."""
    from agentgraph.cli_query import cmd_get

    cmd_get(entity_id=entity_id, as_json=json)


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
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Traverse the graph from an entity."""
    from agentgraph.cli_query import cmd_traverse

    cmd_traverse(entity_id=entity_id, max_depth=depth, as_json=json)


@app.command()
def fetch(
    platform: str = typer.Argument(..., help="Platform name (e.g. gdocs, slack, discord)"),
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
def onboard() -> None:
    """Interactive setup: authenticate with Google Docs, Slack, and Discord."""
    import typer

    from agentgraph.auth.discord import run_token_flow as discord_flow
    from agentgraph.auth.google import run_oauth_flow
    from agentgraph.auth.slack import run_cookie_flow

    typer.echo("=== AgentGraph Setup ===\n")

    typer.echo("Step 1/3: Google Docs")
    run_oauth_flow()

    typer.echo("\nStep 2/3: Slack")
    run_cookie_flow()

    typer.echo("\nStep 3/3: Discord")
    discord_flow()

    typer.echo("\nSetup complete. Run `agentgraph serve` to start the server.")


@app.command()
def mcp_serve() -> None:
    """Start the AgentGraph MCP server (stdio transport)."""
    import asyncio

    from agentgraph.backends import get_backend_class
    from agentgraph.config import get_settings
    from agentgraph.core.context import set_backend

    settings = get_settings()
    backend_class = get_backend_class(settings.backend)
    if settings.backend == "postgres":
        backend = backend_class(settings.database_url)
    elif settings.backend == "sqlite":
        backend = backend_class(settings.backend_sqlite_path, settings.backend_sqlite_vector_mode)
    else:
        backend = backend_class(settings)

    asyncio.run(backend.initialize())
    set_backend(backend)

    from agentgraph.mcp.server import mcp

    mcp.run(transport="stdio")


@app.command()
def migrate(
    from_backend: str = typer.Option("postgres", "--from", help="Source backend name"),
    to_backend: str = typer.Option("sqlite", "--to", help="Destination backend name"),
) -> None:
    """Migrate entities and sync cursors from one backend to another.

    Embeddings are recomputed for all migrated entities.
    Edges are not migrated — connectors will rebuild them on the next sync.
    """
    import asyncio

    asyncio.run(_migrate_async(from_backend, to_backend))


async def _migrate_async(from_backend: str, to_backend: str) -> None:
    from agentgraph.backends import get_backend_class
    from agentgraph.config import get_settings
    from agentgraph.connectors.base import EntityBatch, EntityRecord
    from agentgraph.core.context import set_backend
    from agentgraph.graph.upsert import upsert_batch

    settings = get_settings()

    def _make_backend(name: str) -> object:
        cls = get_backend_class(name)
        if name == "postgres":
            return cls(settings.database_url)
        return cls(settings.backend_sqlite_path, settings.backend_sqlite_vector_mode)

    src = _make_backend(from_backend)
    dst = _make_backend(to_backend)

    typer.echo(f"Initialising {from_backend} source…")
    await src.initialize()  # type: ignore[union-attr]

    typer.echo(f"Initialising {to_backend} destination…")
    await dst.initialize()  # type: ignore[union-attr]
    set_backend(dst)  # type: ignore[arg-type]

    # --- Migrate entities ---
    typer.echo("Reading entities from source…")
    from datetime import datetime

    entity_results = await src.list_entities(  # type: ignore[union-attr]
        entity_types=None, platform=None, since=None, limit=1_000_000
    )
    typer.echo(f"Migrating {len(entity_results)} entities…")

    batch = EntityBatch()
    for e in entity_results:
        ca = e.get("created_at")
        ua = e.get("updated_at")
        batch.entities.append(EntityRecord(
            entity_type=e["entity_type"],
            platform=e["platform"],
            platform_entity_id=e["platform_entity_id"],
            title=e.get("title"),
            content=e.get("content"),
            metadata=e.get("metadata") or {},
            created_at=datetime.fromisoformat(ca) if ca else None,
            updated_at=datetime.fromisoformat(ua) if ua else None,
        ))

    await upsert_batch(batch)
    typer.echo(f"  {len(batch.entities)} entities written.")

    # --- Migrate sync cursors ---
    known_sources = ["slack", "gmail", "gdocs", "gdrive", "gsheets", "discord"]
    for source in known_sources:
        cursor = await src.load_cursor(source)  # type: ignore[union-attr]
        if cursor:
            await dst.save_cursor(source, cursor)  # type: ignore[union-attr]
            typer.echo(f"  Cursor migrated: {source}")

    await src.close()  # type: ignore[union-attr]
    await dst.close()  # type: ignore[union-attr]
    typer.echo("Migration complete.")


@app.command()
def poll(
    source: str | None = typer.Argument(None, help="Connector source to poll (e.g. slack, gmail). Omit to poll all."),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Trigger a background poll for one or all connectors."""
    from agentgraph.cli_query import cmd_poll

    cmd_poll(source=source, as_json=json)


@app.command()
def query(
    entity_type: str = typer.Option(..., "--type", "-t", help="Entity type to query"),
    filter: list[str] = typer.Option([], "--filter", "-f", help="key=value filters (column or metadata)"),
    since: str | None = typer.Option(None, "--since", "-s", help="Only results after this time: ISO timestamp or relative (12h, 30m, 2d)"),
    mine: bool = typer.Option(False, "--mine", "-m", help="Only entities authored by me"),
    limit: int = typer.Option(50, "--limit", "-n", help="Maximum results"),
    order_by: str = typer.Option("created_at", "--order-by", "-o", help="Column to sort by (created_at, updated_at, last_accessed)"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Query entities by type and filters."""
    from agentgraph.cli_query import cmd_query

    parsed_filters = dict(f.split("=", 1) for f in filter if "=" in f)
    cmd_query(entity_type=entity_type, filters=parsed_filters, limit=limit, order_by=order_by, since=since, authored_by_me=mine, as_json=json)
