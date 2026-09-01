"""The two query transports must produce identical CLI output.

`agentgraph <cmd> --json` prints `json.dumps(result, default=str)`, so that is what
these tests compare: whatever the user actually sees. Anything that only shows up
after a JSON round-trip — a tuple serialised as a list, a datetime as a string, an
extra viewer-only field — is caught here rather than in the terminal.

The HTTP client runs against the FastAPI app through `httpx.ASGITransport`, so no
server, socket, or port is involved. ASGITransport does not run the app's lifespan,
so the routes resolve `get_backend()` to the backend this test already installed.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio

from agentgraph.core.context import clear_backend, set_backend
from agentgraph.query_client import HttpQueryClient, InProcessQueryClient, QueryClient
from agentgraph.server.app import app


def _as_cli_json(value: object) -> str:
    """Serialise the way `cli_query` does before printing."""
    return json.dumps(value, default=str, sort_keys=True)


@pytest_asyncio.fixture
async def seeded_clients() -> AsyncIterator[tuple[QueryClient, QueryClient, dict[str, Any]]]:
    from agentgraph.backends.sqlite.backend import SQLiteBackend
    from agentgraph.connectors.base import EntityBatch, EntityRecord

    backend = SQLiteBackend(":memory:")
    await backend.initialize()
    set_backend(backend)
    try:
        await backend.upsert_batch(
            EntityBatch(
                entities=[
                    EntityRecord(
                        entity_type="Document",
                        platform="web",
                        platform_entity_id=f"doc-{index}",
                        title=f"Roadmap {index}",
                        content=f"roadmap planning content {index}",
                        metadata={"web_url": f"https://example.com/{index}"},
                    )
                    for index in range(3)
                ]
            ),
            person_embeddings={},
            entity_embeddings={},
        )
        listed = await backend.list_entities(None, None, None, 10)
        anchor = dict(listed[0])

        in_process = InProcessQueryClient()
        over_http = HttpQueryClient(
            "http://parity.test",
            transport=httpx.ASGITransport(app=app),
        )
        yield in_process, over_http, anchor
    finally:
        clear_backend()
        await backend.close()


@pytest.mark.asyncio
async def test_search_output_matches(
    seeded_clients: tuple[QueryClient, QueryClient, dict[str, Any]],
) -> None:
    in_process, over_http, _ = seeded_clients

    args = ("roadmap", None, 10, 0.0, None)
    assert _as_cli_json(await in_process.search(*args)) == _as_cli_json(
        await over_http.search(*args)
    )


@pytest.mark.asyncio
async def test_search_with_filters_matches(
    seeded_clients: tuple[QueryClient, QueryClient, dict[str, Any]],
) -> None:
    in_process, over_http, _ = seeded_clients

    args = ("roadmap", ["Document"], 2, 0.0, "web")
    assert _as_cli_json(await in_process.search(*args)) == _as_cli_json(
        await over_http.search(*args)
    )


@pytest.mark.asyncio
async def test_get_entity_matches(
    seeded_clients: tuple[QueryClient, QueryClient, dict[str, Any]],
) -> None:
    in_process, over_http, anchor = seeded_clients
    entity_id = str(anchor["id"])

    assert _as_cli_json(await in_process.get_entity(entity_id, False)) == _as_cli_json(
        await over_http.get_entity(entity_id, False)
    )


@pytest.mark.asyncio
async def test_missing_entity_is_none_on_both_transports(
    seeded_clients: tuple[QueryClient, QueryClient, dict[str, Any]],
) -> None:
    """A 404 would make the HTTP client raise where in-process returns None."""
    in_process, over_http, _ = seeded_clients

    assert await in_process.get_entity("no-such-entity", False) is None
    assert await over_http.get_entity("no-such-entity", False) is None


@pytest.mark.asyncio
async def test_edges_match_including_the_resolved_entity(
    seeded_clients: tuple[QueryClient, QueryClient, dict[str, Any]],
) -> None:
    in_process, over_http, anchor = seeded_clients
    entity_id = str(anchor["id"])

    local_entity, local_edges = await in_process.edges(entity_id, None, "both")
    remote_entity, remote_edges = await over_http.edges(entity_id, None, "both")

    # cli_query needs the entity for its None check and the canonical id it prints.
    assert _as_cli_json(local_entity) == _as_cli_json(remote_entity)
    assert _as_cli_json(local_edges) == _as_cli_json(remote_edges)


@pytest.mark.asyncio
async def test_edges_for_missing_entity_match(
    seeded_clients: tuple[QueryClient, QueryClient, dict[str, Any]],
) -> None:
    in_process, over_http, _ = seeded_clients

    local_entity, local_edges = await in_process.edges("no-such-entity", None, "both")
    remote_entity, remote_edges = await over_http.edges("no-such-entity", None, "both")

    assert local_entity is None
    assert remote_entity is None
    assert local_edges == remote_edges == []


@pytest.mark.asyncio
async def test_traverse_matches(
    seeded_clients: tuple[QueryClient, QueryClient, dict[str, Any]],
) -> None:
    in_process, over_http, anchor = seeded_clients
    entity_id = str(anchor["id"])

    local_entity, local_result = await in_process.traverse(entity_id, 2, False)
    remote_entity, remote_result = await over_http.traverse(entity_id, 2, False)

    assert _as_cli_json(local_entity) == _as_cli_json(remote_entity)
    assert _as_cli_json(local_result) == _as_cli_json(remote_result)


@pytest.mark.asyncio
async def test_query_by_filter_matches(
    seeded_clients: tuple[QueryClient, QueryClient, dict[str, Any]],
) -> None:
    in_process, over_http, _ = seeded_clients

    args = ("Document", {"platform": "web"}, 10, "observed_at", None, False, False)
    assert _as_cli_json(await in_process.query_by_filter(*args)) == _as_cli_json(
        await over_http.query_by_filter(*args)
    )


@pytest.mark.asyncio
async def test_query_by_filter_with_no_filters_matches(
    seeded_clients: tuple[QueryClient, QueryClient, dict[str, Any]],
) -> None:
    """An empty filter mapping must survive being sent as a JSON body."""
    in_process, over_http, _ = seeded_clients

    no_filters: dict[str, str] = {}
    args = ("Document", no_filters, 10, "observed_at", None, False, False)
    assert _as_cli_json(await in_process.query_by_filter(*args)) == _as_cli_json(
        await over_http.query_by_filter(*args)
    )


@pytest.mark.asyncio
async def test_http_client_reraises_value_error_with_the_same_message(
    seeded_clients: tuple[QueryClient, QueryClient, dict[str, Any]],
) -> None:
    """A 400 must surface as the ValueError the CLI's error handler expects."""
    in_process, over_http, _ = seeded_clients

    with pytest.raises(ValueError) as local:
        await in_process.delete("no-such-entity")
    with pytest.raises(ValueError) as remote:
        await over_http.delete("no-such-entity")

    assert str(local.value) == str(remote.value)
