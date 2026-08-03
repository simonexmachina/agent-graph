"""HTTP-level benchmark workloads for the public CLI API."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from agentgraph.backends.sqlite.backend import SQLiteBackend
from agentgraph.core.context import clear_backend, set_backend
from agentgraph.server.cli_api import router as cli_router
from benchmarks.corpus import query_vector, seed_sqlite_database
from benchmarks.models import BenchmarkRun, CorpusSpec
from benchmarks.runner import evaluate_search_quality, measure_workload


async def run_api_suite(
    database_path: Path,
    spec: CorpusSpec,
    *,
    iterations: int = 10,
    warmup_iterations: int = 3,
    vector_mode: str = "numpy",
) -> BenchmarkRun:
    """Measure HTTP route composition against a deterministic, seeded database."""
    seeded = await seed_sqlite_database(database_path, spec, vector_mode)
    backend = SQLiteBackend(str(database_path), vector_mode=vector_mode)
    await backend.initialize()
    set_backend(backend)
    hub = await backend.get_entity_by_platform("benchmark", seeded.hub_platform_id)
    if hub is None:
        await backend.close()
        clear_backend()
        raise RuntimeError("Seeded benchmark hub was not persisted")
    app = FastAPI()
    app.include_router(cli_router)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://benchmark") as client:
            with patch(
                "agentgraph.graph.query._cached_query_embedding",
                return_value=tuple(query_vector(17 % spec.cluster_count, spec.cluster_count)),
            ):
                workloads = [
                    await measure_workload(
                        "api.search.exact",
                        lambda: _get_json(
                            client, "/api/cli/search", {"q": seeded.exact_query, "min_score": 0}
                        ),
                        iterations=iterations,
                        warmup_iterations=warmup_iterations,
                        kind="api",
                        quality=evaluate_search_quality(
                            [seeded.exact_platform_id], must_return_ids=[seeded.exact_platform_id]
                        ),
                    ),
                    await measure_workload(
                        "api.viewer_nodes",
                        lambda: _get_json(
                            client,
                            "/api/cli/browse/nodes",
                            {"page": 1, "size": 50, "limit": 500},
                        ),
                        iterations=iterations,
                        warmup_iterations=warmup_iterations,
                        kind="api",
                    ),
                    await measure_workload(
                        "api.graph_traversal",
                        lambda: _get_json(client, f"/api/cli/traverse/{hub['id']}", {"depth": 2}),
                        iterations=iterations,
                        warmup_iterations=warmup_iterations,
                        kind="api",
                    ),
                ]
    finally:
        clear_backend()
        await backend.close()
    return BenchmarkRun(
        git_sha=None,
        corpus=spec,
        vector_mode=vector_mode,
        cold=False,
        workloads=workloads,
    )


async def _get_json(
    client: httpx.AsyncClient, path: str, params: dict[str, str | int]
) -> list[dict[str, object]] | dict[str, object]:
    response = await client.get(path, params=params)
    response.raise_for_status()
    payload: object = response.json()
    if not isinstance(payload, list | dict):
        raise RuntimeError(f"Unexpected API response for {path}")
    return cast(list[dict[str, object]] | dict[str, object], payload)
