"""CLI query commands — call the running server when available, fall back to local."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from typing import Any

import httpx
from rich.console import Console
from rich.table import Table

from agentgraph.config import get_settings

console = Console()


def _server_base() -> str:
    s = get_settings()
    return f"http://{s.server_host}:{s.server_port}/api/cli"


def _get(path: str, params: dict[str, Any] | None = None) -> Any | None:
    """
    GET from the server's CLI API.  Returns parsed JSON on success, None if the
    server is unreachable (connection refused / timeout).
    """
    try:
        resp = httpx.get(
            f"{_server_base()}{path}",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        return None
    except httpx.TimeoutException:
        return None


def _post(path: str, params: dict[str, Any] | None = None) -> Any | None:
    """POST to the server's CLI API. Returns parsed JSON on success, None if unreachable."""
    try:
        resp = httpx.post(
            f"{_server_base()}{path}",
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        return None
    except httpx.TimeoutException:
        return None


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _run_local(coro: Awaitable[Any]) -> Any:
    async def _with_backend() -> Any:
        from agentgraph.connectors.registry import bootstrap
        from agentgraph.core.runtime import backend_context

        bootstrap()
        async with backend_context():
            return await coro

    return _run(_with_backend())


def _warn_local() -> None:
    console.print(
        "[dim]Server not running — using local DB (embedding model will load)[/dim]"
    )


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
    if results is None:
        _warn_local()
        from agentgraph.graph.query import search_entities
        results = _run_local(search_entities(
            query, entity_types=entity_types or None, limit=limit, min_score=min_score, platform=platform
        ))

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
        _warn_local()
        from agentgraph.graph.query import get_entity, get_entity_by_url

        entity = _run_local(get_entity_by_url(entity_id) if target_is_url else get_entity(entity_id))

    if entity is None:
        console.print(f"[red]Entity {entity_id!r} not found.[/red]")
        return

    if resolve and _is_stub(entity):
        console.print("[dim]Stub entity — fetching from source…[/dim]")
        fetch_result = _post("/fetch-entity", params={"entity_id": entity["id"]})
        refreshed = _get(f"/entity/{entity['id']}") if fetch_result is not None else None
        if refreshed is None:
            from agentgraph.graph.fetch import fetch_entity_by_id
            from agentgraph.graph.query import get_entity

            try:
                _run_local(fetch_entity_by_id(entity["id"]))
                refreshed = _run_local(get_entity(entity["id"]))
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
        if refreshed is not None:
            entity = refreshed

    if as_json:
        console.print_json(json.dumps(entity, default=str))
        return

    console.print(f"[bold]{entity['entity_type']}[/bold] — {entity['platform']}")
    console.print(f"[dim]{entity['id']}[/dim]")
    if entity.get("title"):
        _print_field("Title", entity["title"])
    if entity.get("content"):
        console.print("\n[bold]Content:[/bold]")
        console.print(str(entity["content"]), markup=False, highlight=False)
    if entity.get("metadata"):
        _print_field("Metadata", entity["metadata"])


# ---------------------------------------------------------------------------
# edges
# ---------------------------------------------------------------------------

def cmd_edges(
    entity_id: str, edge_type: str | None, direction: str, as_json: bool
) -> None:
    params: dict[str, Any] = {"direction": direction}
    if edge_type:
        params["edge_type"] = edge_type

    edges = _get(f"/edges/{entity_id}", params)
    if edges is None:
        _warn_local()
        from agentgraph.graph.query import get_edges, get_entity
        entity = _run_local(get_entity(entity_id))
        if entity is None:
            console.print(f"[red]Entity {entity_id!r} not found.[/red]")
            return
        edges = _run_local(get_edges(entity["id"], edge_type=edge_type, direction=direction))

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
    result = _get(f"/traverse/{entity_id}", {"depth": max_depth})
    if result is None:
        _warn_local()
        from agentgraph.graph.query import get_entity, traverse_graph
        entity = _run_local(get_entity(entity_id))
        if entity is None:
            console.print(f"[red]Entity {entity_id!r} not found.[/red]")
            return
        result = _run_local(traverse_graph(entity["id"], max_depth=max_depth))

    if resolve and result:
        stubs = [n for n in result.get("nodes", []) if _is_stub(n)]
        if stubs:
            console.print(f"[dim]Resolving {len(stubs)} stub node(s)…[/dim]")
            for stub in stubs:
                fetch_result = _post("/fetch-entity", params={"entity_id": stub["id"]})
                if fetch_result is None:
                    from agentgraph.graph.fetch import fetch_entity_by_id

                    try:
                        _run_local(fetch_entity_by_id(stub["id"]))
                    except ValueError as exc:
                        console.print(f"[red]{exc}[/red]")
            refreshed = _get(f"/traverse/{entity_id}", {"depth": max_depth})
            if refreshed is None:
                from agentgraph.graph.query import get_entity, traverse_graph

                entity = _run_local(get_entity(entity_id))
                if entity is not None:
                    refreshed = _run_local(traverse_graph(entity["id"], max_depth=max_depth))
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
    if result is None:
        _warn_local()
        from agentgraph.graph.fetch import fetch_entity
        try:
            result = _run_local(fetch_entity(platform, resource_id))
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
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
    if result is None:
        _warn_local()
        from agentgraph.graph.fetch import fetch_entity_by_id
        try:
            result = _run_local(fetch_entity_by_id(entity_id))
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return

    if as_json:
        console.print_json(json.dumps(result, default=str))
        return

    console.print(
        f"[green]Fetched:[/green] {result['entities']} entities, "
        f"{result['persons']} persons, {result['edges']} edges"
    )


def cmd_download(entity_id: str, output_path: str | None, as_json: bool) -> None:
    async def _download() -> dict[str, Any]:
        from agentgraph.core.runtime import backend_context
        from agentgraph.graph.download import download_entity

        async with backend_context():
            return await download_entity(entity_id, output_path)

    try:
        result = _run(_download())
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
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
        if exc.response.status_code == 404 and detail == "Not Found":
            result = None
        else:
            console.print(f"[red]{detail}[/red]")
            return
    if result is None:
        _warn_local()
        from agentgraph.core.runtime import backend_context
        from agentgraph.graph.bookmark import bookmark_target, set_entity_bookmark

        async def _bookmark() -> dict[str, Any]:
            async with backend_context():
                if bookmarked:
                    return await bookmark_target(target)
                return await set_entity_bookmark(target, False)

        try:
            result = _run(_bookmark())
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
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
        if exc.response.status_code == 404 and detail == "Not Found":
            result = None
        else:
            console.print(f"[red]{detail}[/red]")
            return
    if result is None:
        _warn_local()
        from agentgraph.core.runtime import backend_context
        from agentgraph.graph.delete import delete_entity

        async def _delete() -> dict[str, Any]:
            async with backend_context():
                return await delete_entity(target)

        try:
            result = _run(_delete())
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
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
    if result is None:
        _warn_local()
        from agentgraph.graph.person import unify_persons

        try:
            result = _run_local(unify_persons(primary_entity_id, duplicate_entity_ids))
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return

    if as_json:
        console.print_json(json.dumps(result, default=str))
        return

    primary = result["primary"]
    console.print(
        f"[green]Unified:[/green] {result['merged_count']} duplicate person(s) into "
        f"{primary.get('title') or primary['platform_entity_id']} [{primary['id'][:8]}]"
    )


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
    if results is None:
        _warn_local()
        from agentgraph.graph.query import query_by_filter
        results = _run_local(
            query_by_filter(
                entity_type,
                filters=filters,
                limit=limit,
                order_by=order_by,
                since=since,
                authored_by_me=authored_by_me,
                has_attachments=has_attachments,
            )
        )

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
    if result is None:
        console.print("[red]Server not available. Start with: agentgraph serve[/red]")
        return

    if as_json:
        console.print_json(json.dumps(result, default=str))
        return

    polled: list[str] = result.get("polled", [])
    if polled:
        console.print(f"[green]Polled:[/green] {', '.join(polled)}")
    else:
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
    if result is None:
        console.print("[red]Server not available. Start with: agentgraph serve[/red]")
        return

    if as_json:
        console.print_json(json.dumps(result, default=str))
        return

    console.print(
        f"[green]Ingest started[/green] for [bold]{result.get('source')}[/bold] — "
        "progress in server logs (agentgraph serve)"
    )
