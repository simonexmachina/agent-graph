"""HTTP endpoints for server-owned manual polling and historical ingestion."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.post("/poll")
async def poll_connectors(
    source: str | None = Query(default=None),
) -> dict[str, Any]:
    """Queue a background poll for one connector or all polling connectors."""
    from agentgraph.connectors.registry import get_all_connectors, get_connector
    from agentgraph.server.sync import schedule_poll_connector

    if source is not None:
        connector = get_connector(source)
        if connector is None:
            raise HTTPException(
                status_code=404,
                detail=f"No connector registered for source '{source}'",
            )
        connectors = [connector]
    else:
        connectors = get_all_connectors()

    polled: list[str] = []
    already_running: list[str] = []
    skipped: list[dict[str, str | None]] = []
    for connector in connectors:
        if connector.poll_interval is None:
            continue
        result = await schedule_poll_connector(connector)
        if result["status"] == "queued":
            polled.append(connector.source)
        elif result["status"] == "already_running":
            already_running.append(connector.source)
        else:
            skipped.append({"source": connector.source, "reason": result["reason"]})

    return {"polled": polled, "already_running": already_running, "skipped": skipped}


@router.post("/ingest")
async def ingest_connector(
    source: str = Query(...),
    account_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Start a connector-owned historical ingest and return immediately."""
    from agentgraph.connectors.registry import get_connector
    from agentgraph.server.sync import run_ingest

    connector = get_connector(source)
    if connector is None:
        raise HTTPException(
            status_code=404,
            detail=f"No connector registered for source '{source}'",
        )

    account_ids = [account_id] if account_id is not None else None
    asyncio.create_task(run_ingest(connector, account_ids=account_ids))
    return {"source": source, "status": "started", "account_id": account_id}
