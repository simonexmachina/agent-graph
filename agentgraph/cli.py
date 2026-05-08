"""AgentGraph CLI entry point."""

from __future__ import annotations

import typer

from agentgraph.connectors.base import BaseConnector

app = typer.Typer(
    name="agentgraph",
    help="Local knowledge graph for AI agents.",
    no_args_is_help=True,
)



@app.command()
def auth(
    platform: str = typer.Argument(..., help="Platform to authenticate (e.g. google, slack, discord)"),
) -> None:
    """Authenticate with a platform connector."""
    from agentgraph.connectors.registry import bootstrap, get_all_connectors

    bootstrap()
    seen: dict[str, BaseConnector] = {}
    for connector in get_all_connectors():
        label: str = getattr(connector, "auth_label", None) or connector.source
        if label not in seen:
            seen[label] = connector

    if platform not in seen:
        available = ", ".join(sorted(seen))
        typer.echo(f"Unknown platform '{platform}'. Available: {available}", err=True)
        raise typer.Exit(code=1)

    type(seen[platform]).run_auth_flow()


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


def _save_user_config(key: str, value: str) -> None:
    """Persist a setting to ~/.agentgraph/.env."""
    from agentgraph.config import CONFIG_DIR

    env_file = CONFIG_DIR / ".env"
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    lines = env_file.read_text().splitlines() if env_file.exists() else []
    prefix = f"{key}="
    new_line = f"{key}={value}"
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = new_line
            break
    else:
        lines.append(new_line)
    env_file.write_text("\n".join(lines) + "\n")


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
def ingest(
    source: str = typer.Argument(..., help="Connector source to ingest (e.g. gmail)"),
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


_DOCKER_COMPOSE = """\
services:
  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_USER: agentgraph
      POSTGRES_PASSWORD: agentgraph
      POSTGRES_DB: agentgraph
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agentgraph"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
"""

_DATABASE_URL = "postgresql://agentgraph:agentgraph@localhost:5432/agentgraph"


@app.command("use-postgres")
def use_postgres(
    database_url: str = typer.Option(
        _DATABASE_URL,
        "--url",
        help="PostgreSQL connection URL",
    ),
    compose_path: str = typer.Option(
        "docker-compose.yml",
        "--compose-out",
        help="Where to write the docker-compose.yml (use '-' to print to stdout)",
    ),
) -> None:
    """Switch to PostgreSQL backend and generate a docker-compose.yml.

    Writes docker-compose.yml to the current directory, saves AGENTGRAPH_BACKEND=postgres
    and AGENTGRAPH_DATABASE_URL to ~/.agentgraph/.env, then prints next steps.
    """

    # Write docker-compose
    if compose_path == "-":
        typer.echo(_DOCKER_COMPOSE, nl=False)
    else:
        from pathlib import Path
        out = Path(compose_path)
        if out.exists():
            typer.echo(f"  {compose_path} already exists — skipping.")
        else:
            out.write_text(_DOCKER_COMPOSE)
            typer.echo(f"  Written {compose_path}")

    # Persist config
    _save_user_config("AGENTGRAPH_BACKEND", "postgres")
    _save_user_config("AGENTGRAPH_DATABASE_URL", database_url)
    typer.echo(f"  Config saved to ~/.agentgraph/.env (backend=postgres, url={database_url})")

    if compose_path != "-":
        typer.echo("\nNext steps:")
        typer.echo("  1. docker compose up -d")
        typer.echo("  2. agentgraph serve")
