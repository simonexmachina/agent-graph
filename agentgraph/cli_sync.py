"""CLI commands that intentionally queue work through the local server."""

from __future__ import annotations

import json
from typing import Any, NoReturn, cast

import httpx
from rich.console import Console

from agentgraph.config import get_settings

console = Console()
POST_TIMEOUT = httpx.Timeout(30, connect=0.5)


def _server_base() -> str:
    settings = get_settings()
    return f"http://{settings.server_host}:{settings.server_port}/api/sync"


def _server_unavailable(exc: Exception) -> NoReturn:
    console.print(
        f"[red]AgentGraph server is not available at {_server_base()}.[/red]\n"
        "Start it with: [bold]agentgraph serve[/bold]",
    )
    raise SystemExit(1) from exc


def _post(path: str, params: dict[str, Any] | None = None) -> Any:
    try:
        response = httpx.post(
            f"{_server_base()}{path}",
            params=params,
            timeout=POST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        _server_unavailable(exc)


def _http_error_detail(exc: httpx.HTTPStatusError) -> str:
    try:
        return str(exc.response.json().get("detail", str(exc)))
    except Exception:
        return str(exc)


def cmd_poll(source: str | None, as_json: bool) -> None:
    params: dict[str, Any] = {}
    if source:
        params["source"] = source
    try:
        result = _post("/poll", params=params)
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]{_http_error_detail(exc)}[/red]")
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


def queue_connector_poll(source: str) -> dict[str, str | None]:
    """Queue one connector through the server and normalize its schedule result."""
    try:
        result = cast(dict[str, Any], _post("/poll", params={"source": source}))
    except httpx.HTTPStatusError as exc:
        raise ValueError(_http_error_detail(exc)) from exc

    if source in cast(list[str], result.get("polled", [])):
        return {"source": source, "status": "queued", "reason": None}
    if source in cast(list[str], result.get("already_running", [])):
        return {"source": source, "status": "already_running", "reason": None}

    skipped = cast(list[dict[str, str | None]], result.get("skipped", []))
    reason = next(
        (item.get("reason") for item in skipped if item.get("source") == source),
        "poll was not queued",
    )
    return {"source": source, "status": "skipped", "reason": reason}


def queue_connector_ingest(source: str, account_id: str | None = None) -> dict[str, Any]:
    """Queue a connector-owned historical ingest through the server."""
    params: dict[str, Any] = {"source": source}
    if account_id is not None:
        params["account_id"] = account_id
    try:
        return cast(dict[str, Any], _post("/ingest", params=params))
    except httpx.HTTPStatusError as exc:
        raise ValueError(_http_error_detail(exc)) from exc
