"""CLI query commands backed by the running AgentGraph server."""

from __future__ import annotations

import json
from typing import Any, NoReturn

import httpx
from rich.console import Console
from rich.table import Table

from agentgraph.config import get_settings

console = Console()
GET_TIMEOUT = httpx.Timeout(10, connect=0.5)
POST_TIMEOUT = httpx.Timeout(30, connect=0.5)


def _server_base() -> str:
    s = get_settings()
    return f"http://{s.server_host}:{s.server_port}/api/cli"


def _server_unavailable(exc: Exception) -> NoReturn:
    console.print(
        f"[red]AgentGraph server is not available at {_server_base()}.[/red]\n"
        "Start it with: [bold]agentgraph serve[/bold]",
    )
    raise SystemExit(1) from exc


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET from the server's CLI API and return parsed JSON."""
    try:
        resp = httpx.get(
            f"{_server_base()}{path}",
            params=params,
            timeout=GET_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        _server_unavailable(exc)


def _post(path: str, params: dict[str, Any] | None = None) -> Any:
    """POST to the server's CLI API and return parsed JSON."""
    try:
        resp = httpx.post(
            f"{_server_base()}{path}",
            params=params,
            timeout=POST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        _server_unavailable(exc)


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

def cmd_search(
    query: str,
    entity_types: list[str],
    limit: int,
    min_score: float,
    as_json: bool,
    platform: str | None = None,
) -> None:
    params: dict[str, Any] = {"q": query, "limit": limit, "min_score": min_score}
    if entity_types:
        params["entity_type"] = entity_types
    if platform:
        params["platform"] = platform

    results = _get("/search", params)

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

def _is_stub(entity: dict[str, Any]) -> bool:
    """Return True if the entity has no meaningful content (stub / unfetched)."""
    return not entity.get("title") and not entity.get("content")


def _print_field(label: str, value: object) -> None:
    console.print(f"\n[bold]{label}:[/bold] ", end="")
    console.print(str(value), markup=False, highlight=False)


def _print_entity(entity: dict[str, Any]) -> None:
    """Render an entity in the same detail format used by ``agentgraph get``."""
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
    from agentgraph.graph.query import is_http_url

    target_is_url = is_http_url(entity_id)
    try:
        entity = (
            _get("/entity-by-url", {"url": entity_id})
            if target_is_url
            else _get(f"/entity/{entity_id}")
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
        entity = None
    if entity is None:
        console.print(f"[red]Entity {entity_id!r} not found.[/red]")
        return

    if resolve and _is_stub(entity):
        console.print("[dim]Stub entity — fetching from source…[/dim]")
        _post("/fetch-entity", params={"entity_id": entity["id"]})
        refreshed = _get(f"/entity/{entity['id']}")
        if refreshed is not None:
            entity = refreshed

    if as_json:
        console.print_json(json.dumps(entity, default=str))
        return

    _print_entity(entity)


# ---------------------------------------------------------------------------
# edges
# ---------------------------------------------------------------------------

def cmd_edges(
    entity_id: str, edge_type: str | None, direction: str, as_json: bool
) -> None:
    params: dict[str, Any] = {"direction": direction}
    if edge_type:
        params["edge_type"] = edge_type

    try:
        edges = _get(f"/edges/{entity_id}", params)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
        console.print(f"[red]Entity {entity_id!r} not found.[/red]")
        return

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
        if e.get("source_entity_id") == entity_id:
            direction_label = "→ out"
            other = e.get("target_ref") or e.get("target_entity_id") or "?"
        else:
            direction_label = "← in"
            other = e.get("source_ref") or e.get("source_entity_id") or "?"
        table.add_row(e["edge_type"], direction_label, str(other), e.get("platform") or "")

    console.print(table)


# ---------------------------------------------------------------------------
# traverse
# ---------------------------------------------------------------------------

def cmd_traverse(entity_id: str, max_depth: int, as_json: bool, resolve: bool = False) -> None:
    try:
        result = _get(f"/traverse/{entity_id}", {"depth": max_depth})
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
        console.print(f"[red]Entity {entity_id!r} not found.[/red]")
        return

    if resolve and result:
        stubs = [n for n in result.get("nodes", []) if _is_stub(n)]
        if stubs:
            console.print(f"[dim]Resolving {len(stubs)} stub node(s)…[/dim]")
            for stub in stubs:
                _post("/fetch-entity", params={"entity_id": stub["id"]})
            refreshed = _get(f"/traverse/{entity_id}", {"depth": max_depth})
            if refreshed is not None:
                result = refreshed

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
        stub_marker = " [dim](stub)[/dim]" if _is_stub(n) else ""
        table.add_row(str(n["id"])[:8], n["entity_type"], n["platform"], (n.get("title") or "") + stub_marker)

    console.print(table)


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------

def cmd_fetch(platform: str, resource_id: str, as_json: bool) -> None:
    try:
        result = _post("/fetch", params={"platform": platform, "resource_id": resource_id})
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", str(exc))
        except Exception:
            detail = str(exc)
        console.print(f"[red]{detail}[/red]")
        return
    if as_json:
        console.print_json(json.dumps(result, default=str))
        return

    console.print(
        f"[green]Fetched:[/green] {result['entities']} entities, "
        f"{result['persons']} persons, {result['edges']} edges"
    )


def cmd_fetch_entity(entity_id: str, as_json: bool) -> None:
    try:
        result = _post("/fetch-entity", params={"entity_id": entity_id})
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", str(exc))
        except Exception:
            detail = str(exc)
        console.print(f"[red]{detail}[/red]")
        return
    if as_json:
        console.print_json(json.dumps(result, default=str))
        return

    console.print(
        f"[green]Fetched:[/green] {result['entities']} entities, "
        f"{result['persons']} persons, {result['edges']} edges"
    )


def cmd_download(entity_id: str, output_path: str | None, as_json: bool) -> None:
    try:
        params: dict[str, Any] = {"entity_id": entity_id}
        if output_path is not None:
            params["output_path"] = output_path
        result = _post("/download", params=params)
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", str(exc))
        except Exception:
            detail = str(exc)
        console.print(f"[red]{detail}[/red]")
        return

    if as_json:
        console.print_json(json.dumps(result, default=str))
        return

    console.print(
        f"[green]Downloaded:[/green] {result['filename']} "
        f"({result['bytes']} bytes) → {result['path']}"
    )


def cmd_bookmark(target: str, bookmarked: bool, as_json: bool) -> None:
    try:
        result = _post("/bookmark", params={"target": target, "bookmarked": bookmarked})
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", str(exc))
        except Exception:
            detail = str(exc)
        console.print(f"[red]{detail}[/red]")
        return

    if as_json:
        console.print_json(json.dumps(result, default=str))
        return

    label = result.get("title") or result.get("platform_entity_id") or result["id"]
    action = "Bookmarked" if bookmarked else "Bookmark removed"
    console.print(f"[green]{action}:[/green] {label} [{result['id'][:8]}]")


def cmd_delete(target: str, as_json: bool) -> None:
    try:
        result = _post("/delete", params={"target": target})
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", str(exc))
        except Exception:
            detail = str(exc)
        console.print(f"[red]{detail}[/red]")
        return

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
    try:
        result = _post(
            "/unify-persons",
            params={"primary": primary_entity_id, "duplicate": duplicate_entity_ids},
        )
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", str(exc))
        except Exception:
            detail = str(exc)
        console.print(f"[red]{detail}[/red]")
        return
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
    params: dict[str, Any] = {
        "entity_type": entity_type,
        "limit": limit,
        "order_by": order_by,
        "mine": authored_by_me,
    }
    if since:
        params["since"] = since
    if filters:
        params["filter"] = [f"{k}={v}" for k, v in filters.items()]
    if has_attachments:
        params["has_attachments"] = True

    results = _get("/query", params)

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


def cmd_poll(source: str | None, as_json: bool) -> None:
    params: dict[str, Any] = {}
    if source:
        params["source"] = source
    try:
        result = _post("/poll", params=params)
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", str(exc))
        except Exception:
            detail = str(exc)
        console.print(f"[red]{detail}[/red]")
        return
    if as_json:
        console.print_json(json.dumps(result, default=str))
        return

    polled: list[str] = result.get("polled", [])
    already_running: list[str] = result.get("already_running", [])
    skipped: list[dict[str, str | None]] = result.get("skipped", [])
    if polled:
        console.print(f"[green]Queued poll:[/green] {', '.join(polled)}")
    if already_running:
        console.print(f"[yellow]Already running:[/yellow] {', '.join(already_running)}")
    for item in skipped:
        source_name = item.get("source") or "unknown"
        reason = item.get("reason") or "not available"
        console.print(f"[yellow]Skipped:[/yellow] {source_name} — {reason}")
    if not polled and not already_running and not skipped:
        console.print("[dim]No connectors polled (none matched or none have poll_interval set).[/dim]")


def cmd_ingest(source: str, as_json: bool) -> None:
    try:
        result = _post("/ingest", params={"source": source})
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", str(exc))
        except Exception:
            detail = str(exc)
        console.print(f"[red]{detail}[/red]")
        return
    if as_json:
        console.print_json(json.dumps(result, default=str))
        return

    console.print(
        f"[green]Ingest started[/green] for [bold]{result.get('source')}[/bold] — "
        "progress in server logs (agentgraph serve)"
    )
