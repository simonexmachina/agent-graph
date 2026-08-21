"""CLI graph commands executed directly against the configured backend."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from rich.console import Console
from rich.table import Table

from agentgraph.core.runtime import backend_context
from agentgraph.graph.operations import is_stub, summarize_entities

console = Console()


async def _with_backend[T](operation: Callable[[], Awaitable[T]]) -> T:
    from agentgraph.connectors.registry import bootstrap

    bootstrap()
    async with backend_context():
        return await operation()


def _run[T](
    operation: Callable[[], Awaitable[T]],
    error_hint: Callable[[Exception], str | None] | None = None,
) -> T:
    """Run one graph operation with a configured backend and concise CLI errors."""
    try:
        return asyncio.run(_with_backend(operation))
    except Exception as exc:
        console.print("[red]AgentGraph command failed:[/red] ", end="")
        console.print(str(exc), markup=False, highlight=False)
        hint = error_hint(exc) if error_hint is not None else None
        if hint:
            console.print(hint, markup=False, highlight=False)
        raise SystemExit(1) from exc


def run_graph_operation[T](operation: Callable[[], Awaitable[T]]) -> T:
    """Run a graph operation from another CLI command."""
    return _run(operation)


def cmd_search(
    query: str,
    entity_types: list[str],
    limit: int,
    min_score: float,
    as_json: bool,
    platform: str | None = None,
) -> None:
    async def operation() -> list[dict[str, Any]]:
        from agentgraph.graph.query import search_entities

        results = await search_entities(
            query,
            entity_types=entity_types or None,
            limit=limit,
            min_score=min_score,
            platform=platform,
        )
        return summarize_entities(results)

    results = _run(operation)

    if as_json:
        console.print_json(json.dumps(results, default=str))
        return
    if not results:
        console.print("[dim]No results.[/dim]")
        return

    table = Table(title=f'Search: "{query}"', show_lines=True)
    table.add_column("ID", style="dim", no_wrap=True, max_width=8)
    table.add_column("Type")
    table.add_column("Platform")
    table.add_column("Title / Content", ratio=1)
    table.add_column("Score", justify="right")
    for result in results:
        snippet = (result.get("title") or result.get("content") or "")[:120]
        score = f"{result['score']:.4f}" if result.get("score") else "—"
        table.add_row(
            str(result["id"])[:8],
            str(result["entity_type"]),
            str(result["platform"]),
            str(snippet),
            score,
        )
    console.print(table)


def _print_field(label: str, value: object) -> None:
    console.print(f"\n[bold]{label}:[/bold] ", end="")
    console.print(str(value), markup=False, highlight=False)


def _print_entity(entity: dict[str, Any]) -> None:
    """Render an entity in the detail format used by ``agentgraph get``."""
    console.print(f"[bold]{entity['entity_type']}[/bold] — {entity['platform']}")
    console.print(f"[dim]{entity['id']}[/dim]")
    if entity.get("title"):
        _print_field("Title", entity["title"])
    if entity.get("content"):
        console.print("\n[bold]Content:[/bold]")
        console.print(str(entity["content"]), markup=False, highlight=False)
    if entity.get("metadata"):
        _print_field("Metadata", entity["metadata"])


def cmd_get(entity_id: str, as_json: bool, resolve: bool = False) -> None:
    async def operation() -> dict[str, Any] | None:
        from agentgraph.graph.operations import get_entity_details

        return await get_entity_details(entity_id, resolve=resolve)

    entity = _run(operation)
    if entity is None:
        console.print(f"[red]Entity {entity_id!r} not found.[/red]")
        return
    if as_json:
        console.print_json(json.dumps(entity, default=str))
        return
    _print_entity(entity)


def cmd_edges(
    entity_id: str,
    edge_type: str | None,
    direction: str,
    as_json: bool,
) -> None:
    async def operation() -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        from agentgraph.graph.operations import get_entity_edges

        return await get_entity_edges(
            entity_id,
            edge_type=edge_type,
            direction=direction,
        )

    entity, edges = _run(operation)
    if entity is None:
        console.print(f"[red]Entity {entity_id!r} not found.[/red]")
        return
    if as_json:
        console.print_json(json.dumps(edges, default=str))
        return
    if not edges:
        console.print("[dim]No edges found.[/dim]")
        return

    canonical_id = str(entity["id"])
    table = Table(title=f"Edges for {canonical_id[:8]}…", show_lines=True)
    table.add_column("Type")
    table.add_column("Direction")
    table.add_column("Other end")
    table.add_column("Platform")
    for edge in edges:
        if edge.get("source_entity_id") == canonical_id:
            direction_label = "→ out"
            other = edge.get("target_ref") or edge.get("target_entity_id") or "?"
        else:
            direction_label = "← in"
            other = edge.get("source_ref") or edge.get("source_entity_id") or "?"
        table.add_row(
            str(edge["edge_type"]),
            direction_label,
            str(other),
            str(edge.get("platform") or ""),
        )
    console.print(table)


def cmd_traverse(
    entity_id: str,
    max_depth: int,
    as_json: bool,
    resolve: bool = False,
) -> None:
    async def operation() -> tuple[dict[str, Any] | None, dict[str, Any]]:
        from agentgraph.graph.operations import traverse_entity

        return await traverse_entity(
            entity_id,
            max_depth=max_depth,
            resolve=resolve,
        )

    entity, result = _run(operation)
    if entity is None:
        console.print(f"[red]Entity {entity_id!r} not found.[/red]")
        return
    if as_json:
        console.print_json(json.dumps(result, default=str))
        return

    nodes = result.get("nodes", [])
    edges = result.get("edges", [])
    console.print(f"[bold]Traversal:[/bold] {len(nodes)} nodes, {len(edges)} edges")
    table = Table(title="Nodes", show_lines=True)
    table.add_column("ID", style="dim", max_width=8)
    table.add_column("Type")
    table.add_column("Platform")
    table.add_column("Title")
    for node in nodes:
        stub_marker = " [dim](stub)[/dim]" if is_stub(node) else ""
        table.add_row(
            str(node["id"])[:8],
            str(node["entity_type"]),
            str(node["platform"]),
            str(node.get("title") or "") + stub_marker,
        )
    console.print(table)


def _print_fetch_result(result: dict[str, Any]) -> None:
    console.print(
        f"[green]Fetched:[/green] {result['entities']} entities, "
        f"{result['persons']} persons, {result['edges']} edges"
    )


def cmd_fetch(platform: str, resource_id: str, as_json: bool) -> None:
    async def operation() -> dict[str, Any]:
        from agentgraph.graph.fetch import fetch_entity

        return await fetch_entity(platform, resource_id)

    def error_hint(error: Exception) -> str | None:
        from agentgraph.connectors.registry import get_connector

        connector = get_connector(platform)
        return connector.fetch_error_hint(resource_id, error, "cli") if connector is not None else None

    result = _run(operation, error_hint=error_hint)
    if as_json:
        console.print_json(json.dumps(result, default=str))
        return
    _print_fetch_result(result)


def cmd_fetch_entity(entity_id: str, as_json: bool) -> None:
    async def operation() -> dict[str, Any]:
        from agentgraph.graph.fetch import fetch_entity_by_id

        return await fetch_entity_by_id(entity_id)

    result = _run(operation)
    if as_json:
        console.print_json(json.dumps(result, default=str))
        return
    _print_fetch_result(result)


def cmd_download(entity_id: str, output_path: str | None, as_json: bool) -> None:
    async def operation() -> dict[str, Any]:
        from agentgraph.graph.download import download_entity

        return await download_entity(entity_id, output_path)

    result = _run(operation)
    if as_json:
        console.print_json(json.dumps(result, default=str))
        return
    console.print(
        f"[green]Downloaded:[/green] {result['filename']} "
        f"({result['bytes']} bytes) → {result['path']}"
    )


def cmd_bookmark(target: str, bookmarked: bool, as_json: bool) -> None:
    async def operation() -> dict[str, Any]:
        from agentgraph.graph.bookmark import bookmark_target, set_entity_bookmark

        if bookmarked:
            return await bookmark_target(target)
        return await set_entity_bookmark(target, False)

    result = _run(operation)
    if as_json:
        console.print_json(json.dumps(result, default=str))
        return
    label = result.get("title") or result.get("platform_entity_id") or result["id"]
    action = "Bookmarked" if bookmarked else "Bookmark removed"
    console.print(f"[green]{action}:[/green] {label} [{result['id'][:8]}]")


def cmd_delete(target: str, as_json: bool) -> None:
    async def operation() -> dict[str, Any]:
        from agentgraph.graph.delete import delete_entity

        return await delete_entity(target)

    result = _run(operation)
    if as_json:
        console.print_json(json.dumps(result, default=str))
        return
    entity = result["entity"]
    label = entity.get("title") or entity.get("platform_entity_id") or entity["id"]
    console.print(f"[green]Deleted:[/green] {label} [{entity['id'][:8]}]")


def cmd_unify_persons(
    primary_entity_id: str,
    duplicate_entity_ids: list[str],
    as_json: bool,
) -> None:
    async def operation() -> dict[str, Any]:
        from agentgraph.graph.person import unify_persons

        return await unify_persons(primary_entity_id, duplicate_entity_ids)

    result = _run(operation)
    if as_json:
        console.print_json(json.dumps(result, default=str))
        return
    console.print(
        f"[green]Unified:[/green] {result['merged_count']} duplicate person(s). "
        "Canonical person:"
    )
    _print_entity(result["primary"])


def cmd_query(
    entity_type: str,
    filters: dict[str, str],
    limit: int,
    order_by: str,
    since: str | None,
    authored_by_me: bool,
    as_json: bool,
    has_attachments: bool = False,
) -> None:
    async def operation() -> list[dict[str, Any]]:
        from agentgraph.graph.query import query_by_filter

        results = await query_by_filter(
            entity_type,
            filters=filters,
            limit=limit,
            order_by=order_by,
            since=since,
            authored_by_me=authored_by_me,
            has_attachments=has_attachments,
        )
        return summarize_entities(results)

    results = _run(operation)
    if as_json:
        console.print_json(json.dumps(results, default=str))
        return
    if not results:
        console.print("[dim]No results.[/dim]")
        return

    table = Table(title=f"Query: {entity_type}", show_lines=True)
    table.add_column("ID", style="dim", max_width=8)
    table.add_column("Platform")
    table.add_column("Title / Content", ratio=1)
    for result in results:
        snippet = (result.get("title") or result.get("content") or "")[:120]
        table.add_row(str(result["id"])[:8], str(result["platform"]), str(snippet))
    console.print(table)
