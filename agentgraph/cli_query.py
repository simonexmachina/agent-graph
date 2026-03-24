"""CLI query commands — thin wrappers over the graph query layer."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

def cmd_search(query: str, entity_types: list[str], limit: int, as_json: bool) -> None:
    from agentgraph.graph.query import search_entities

    results = _run(search_entities(query, entity_types=entity_types or None, limit=limit))

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

    for r in results:
        snippet = (r.get("title") or r.get("content") or "")[:120]
        score = f"{r['score']:.4f}" if r.get("score") else "—"
        table.add_row(str(r["id"])[:8], r["entity_type"], r["platform"], snippet, score)

    console.print(table)


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

def cmd_get(entity_id: str, as_json: bool) -> None:
    from agentgraph.graph.query import get_entity

    entity = _run(get_entity(entity_id))

    if entity is None:
        console.print(f"[red]Entity {entity_id!r} not found.[/red]")
        return

    if as_json:
        console.print_json(json.dumps(entity, default=str))
        return

    console.print(f"[bold]{entity['entity_type']}[/bold] — {entity['platform']}")
    console.print(f"[dim]{entity['id']}[/dim]")
    if entity.get("title"):
        console.print(f"\n[bold]Title:[/bold] {entity['title']}")
    if entity.get("content"):
        console.print(f"\n[bold]Content:[/bold]\n{entity['content']}")
    if entity.get("metadata"):
        console.print(f"\n[bold]Metadata:[/bold] {entity['metadata']}")


# ---------------------------------------------------------------------------
# edges
# ---------------------------------------------------------------------------

def cmd_edges(
    entity_id: str, edge_type: str | None, direction: str, as_json: bool
) -> None:
    from agentgraph.graph.query import get_edges

    edges = _run(get_edges(entity_id, edge_type=edge_type, direction=direction))

    if as_json:
        console.print_json(json.dumps(edges, default=str))
        return

    if not edges:
        console.print("[dim]No edges found.[/dim]")
        return

    table = Table(title=f"Edges for {entity_id[:8]}…", show_lines=True)
    table.add_column("Type")
    table.add_column("Direction")
    table.add_column("Other end")
    table.add_column("Platform")

    for e in edges:
        if e.get("source_entity_id") == entity_id or e.get("source_person_id") == entity_id:
            direction_label = "→ out"
            other = e.get("target_ref") or e.get("target_entity_id") or e.get("target_person_id") or "?"
        else:
            direction_label = "← in"
            other = e.get("source_ref") or e.get("source_entity_id") or e.get("source_person_id") or "?"
        table.add_row(e["edge_type"], direction_label, str(other), e.get("platform") or "")

    console.print(table)


# ---------------------------------------------------------------------------
# traverse
# ---------------------------------------------------------------------------

def cmd_traverse(entity_id: str, max_depth: int, as_json: bool) -> None:
    from agentgraph.graph.query import traverse_graph

    result = _run(traverse_graph(entity_id, max_depth=max_depth))

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

    for n in nodes:
        table.add_row(str(n["id"])[:8], n["entity_type"], n["platform"], n.get("title") or "")

    console.print(table)


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------

def cmd_query(
    entity_type: str, filters: dict[str, str], limit: int, as_json: bool
) -> None:
    from agentgraph.graph.query import query_by_filter

    results = _run(query_by_filter(entity_type, filters=filters, limit=limit))

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

    for r in results:
        snippet = (r.get("title") or r.get("content") or "")[:120]
        table.add_row(str(r["id"])[:8], r["platform"], snippet)

    console.print(table)
