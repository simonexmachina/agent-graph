"""Unit tests for the graph query layer and MCP tools (mocked backend)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agentgraph.core.context import set_backend

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entity(
    *,
    entity_type: str = "Document",
    platform: str = "gdocs",
    title: str = "Test Doc",
    content: str = "some content",
    score: float | None = None,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": str(uuid4()),
        "entity_type": entity_type,
        "platform": platform,
        "platform_entity_id": "pe-" + str(uuid4())[:8],
        "title": title,
        "content": content,
        "metadata": {},
        "created_at": None,
        "updated_at": None,
        "bookmarked": False,
    }
    if score is not None:
        base["score"] = score
    return base


def _edge(
    *,
    edge_type: str = "authored",
    source_entity_id: str | None = None,
    target_entity_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "edge_type": edge_type,
        "platform": "gdocs",
        "properties": {},
        "source_entity_id": source_entity_id,
        "target_entity_id": target_entity_id,
        "source_ref": None,
        "target_ref": None,
    }


def _mock_backend(**method_overrides: Any) -> Any:
    """Build a mock StorageBackend with sensible async defaults."""
    backend = MagicMock()
    defaults = {
        "search_entities": AsyncMock(return_value=[]),
        "get_entity_by_id": AsyncMock(return_value=None),
        "get_entities_by_id_prefix": AsyncMock(return_value=[]),
        "get_entity_by_platform": AsyncMock(return_value=None),
        "get_edges": AsyncMock(return_value=[]),
        "get_edges_for_entities": AsyncMock(return_value=[]),
        "traverse_graph": AsyncMock(return_value={"nodes": [], "edges": []}),
        "query_by_filter": AsyncMock(return_value=[]),
        "list_entities": AsyncMock(return_value=[]),
        "touch_last_accessed_by_ids": AsyncMock(return_value=None),
        "get_platform_last_synced_at": AsyncMock(return_value=None),
        "get_platforms_last_synced_at": AsyncMock(return_value={}),
        "set_entity_bookmarked": AsyncMock(return_value=_entity(title="Bookmarked Doc")),
        "delete_entity": AsyncMock(return_value=_entity(title="Deleted Doc")),
    }
    for name, value in {**defaults, **method_overrides}.items():
        setattr(backend, name, value)
    return backend


# ---------------------------------------------------------------------------
# search_entities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_entities_returns_results() -> None:
    from agentgraph.graph.query import search_entities

    expected = [_entity(score=0.9), _entity(score=0.7)]
    backend = _mock_backend(search_entities=AsyncMock(return_value=expected))
    set_backend(backend)

    with patch("agentgraph.graph.embeddings.encode_query", return_value=[0.1] * 384):
        results = await search_entities("test query", limit=5)

    assert len(results) == 2
    assert results[0]["entity_type"] == "Document"


@pytest.mark.asyncio
async def test_search_entities_empty_results() -> None:
    from agentgraph.graph.query import search_entities

    backend = _mock_backend(search_entities=AsyncMock(return_value=[]))
    set_backend(backend)

    with patch("agentgraph.graph.embeddings.encode_query", return_value=[0.0] * 384):
        results = await search_entities("empty query")

    assert results == []


@pytest.mark.asyncio
async def test_search_entities_passes_platform_to_backend() -> None:
    from agentgraph.graph.query import search_entities

    mock_search = AsyncMock(return_value=[])
    backend = _mock_backend(search_entities=mock_search)
    set_backend(backend)

    with patch("agentgraph.graph.embeddings.encode_query", return_value=[0.1] * 384):
        await search_entities("discord stuff", platform="discord")

    mock_search.assert_called_once()
    _, kwargs = mock_search.call_args
    assert kwargs.get("platform") == "discord"


@pytest.mark.asyncio
async def test_search_entities_platform_none_by_default() -> None:
    from agentgraph.graph.query import search_entities

    mock_search = AsyncMock(return_value=[])
    backend = _mock_backend(search_entities=mock_search)
    set_backend(backend)

    with patch("agentgraph.graph.embeddings.encode_query", return_value=[0.1] * 384):
        await search_entities("anything")

    mock_search.assert_called_once()
    _, kwargs = mock_search.call_args
    assert kwargs.get("platform") is None


@pytest.mark.asyncio
async def test_search_entities_offloads_query_embedding() -> None:
    from agentgraph.graph.query import clear_query_embedding_cache, search_entities

    backend = _mock_backend(search_entities=AsyncMock(return_value=[]))
    set_backend(backend)
    calls: list[tuple[Any, tuple[Any, ...]]] = []
    clear_query_embedding_cache()

    async def fake_to_thread(func: Any, *args: Any) -> Any:
        calls.append((func, args))
        return func(*args)

    with (
        patch("agentgraph.graph.embeddings.encode_query", return_value=[0.1] * 384),
        patch("agentgraph.graph.query.asyncio.to_thread", new=fake_to_thread),
    ):
        await search_entities("anything")

    assert len(calls) == 1
    assert calls[0][1] == ("anything",)


@pytest.mark.asyncio
async def test_search_entities_caches_query_embedding() -> None:
    from agentgraph.graph.query import clear_query_embedding_cache, search_entities

    backend = _mock_backend(search_entities=AsyncMock(return_value=[]))
    set_backend(backend)
    clear_query_embedding_cache()

    with patch(
        "agentgraph.graph.embeddings.encode_query", return_value=[0.1] * 384
    ) as encode_query:
        await search_entities("repeat")
        await search_entities("repeat")

    encode_query.assert_called_once_with("repeat")


@pytest.mark.asyncio
async def test_sqlite_search_skips_vector_when_fts_fills_candidate_window() -> None:
    from agentgraph.backends.sqlite.backend import SQLiteBackend
    from agentgraph.connectors.base import EntityBatch, EntityRecord

    backend = SQLiteBackend(":memory:")
    await backend.initialize()
    try:
        await backend.upsert_batch(
            EntityBatch(
                entities=[
                    EntityRecord(
                        entity_type="Document",
                        platform="web",
                        platform_entity_id=f"doc-{index}",
                        title=f"Alpha {index}",
                        content="alpha content",
                    )
                    for index in range(5)
                ]
            ),
            person_embeddings={},
            entity_embeddings={},
        )

        with patch(
            "agentgraph.backends.sqlite.backend.vector_ranked", new=AsyncMock(return_value=[])
        ) as vector_ranked:
            results = await backend.search_entities([0.0] * 384, "alpha", None, 1, 0.0)

        assert len(results) == 1
        vector_ranked.assert_not_awaited()
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_sqlite_search_uses_large_vector_window_for_sparse_fts() -> None:
    from agentgraph.backends.sqlite.backend import SQLiteBackend
    from agentgraph.connectors.base import EntityBatch, EntityRecord

    backend = SQLiteBackend(":memory:")
    await backend.initialize()
    try:
        await backend.upsert_batch(
            EntityBatch(
                entities=[
                    EntityRecord(
                        entity_type="Document",
                        platform="web",
                        platform_entity_id="doc-0",
                        title="Alpha",
                        content="alpha content",
                    )
                ]
            ),
            person_embeddings={},
            entity_embeddings={},
        )

        with patch(
            "agentgraph.backends.sqlite.backend.vector_ranked", new=AsyncMock(return_value=[])
        ) as vector_ranked:
            await backend.search_entities([0.0] * 384, "alpha", None, 1, 0.0)

        vector_ranked.assert_awaited_once()
        assert vector_ranked.call_args.kwargs["candidate_limit"] == 5
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_query_by_filter_reuses_connector_for_web_url_enrichment() -> None:
    from agentgraph.graph.query import query_by_filter

    entities = [
        _entity(platform="example"),
        _entity(platform="example"),
    ]
    backend = _mock_backend(query_by_filter=AsyncMock(return_value=entities))
    set_backend(backend)

    class FakeConnector:
        def entity_url(self, platform_entity_id: str) -> str:
            return f"https://example.com/{platform_entity_id}"

    with patch(
        "agentgraph.connectors.registry.get_connector", return_value=FakeConnector()
    ) as get_connector:
        result = await query_by_filter("Document", {})

    assert result[0]["metadata"]["web_url"].startswith("https://example.com/")
    get_connector.assert_called_once_with("example")


# ---------------------------------------------------------------------------
# get_entity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_entity_found() -> None:
    from agentgraph.graph.query import get_entity

    eid = str(uuid4())
    entity = _entity(title="Found Doc")
    entity["id"] = eid
    backend = _mock_backend(get_entity_by_id=AsyncMock(return_value=entity))
    set_backend(backend)

    result = await get_entity(eid)
    assert result is not None
    assert result["title"] == "Found Doc"


@pytest.mark.asyncio
async def test_get_entity_not_found() -> None:
    from agentgraph.graph.query import get_entity

    backend = _mock_backend(get_entity_by_id=AsyncMock(return_value=None))
    set_backend(backend)

    result = await get_entity(str(uuid4()))
    assert result is None


@pytest.mark.asyncio
async def test_get_entity_by_url_uses_owning_connector() -> None:
    from agentgraph.connectors.base import SourceReference
    from agentgraph.graph.query import get_entity_by_url

    entity = _entity(platform="gdocs", title="URL Doc")
    backend = _mock_backend(get_entity_by_platform=AsyncMock(return_value=entity))
    set_backend(backend)

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch(
            "agentgraph.server.router.classify_url",
            return_value=SourceReference("gdocs", "document", "doc-1"),
        ),
    ):
        result = await get_entity_by_url("https://docs.google.com/document/d/doc-1/edit")

    assert result is entity
    backend.get_entity_by_platform.assert_awaited_once_with("gdocs", "doc-1")


@pytest.mark.asyncio
async def test_get_entity_by_url_uses_web_canonical_url() -> None:
    from agentgraph.connectors.base import SourceReference
    from agentgraph.graph.query import get_entity_by_url

    entity = _entity(platform="web", title="Web Page")
    backend = _mock_backend(get_entity_by_platform=AsyncMock(return_value=entity))
    set_backend(backend)

    class FakeWebConnector:
        def resolve_url(self, url: str) -> SourceReference | None:
            return SourceReference("web", "document", url.removesuffix("#section"))

        def entity_url(self, platform_entity_id: str) -> str:
            return platform_entity_id

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.server.router.classify_url", return_value=None),
        patch("agentgraph.connectors.registry.get_connector", return_value=FakeWebConnector()),
    ):
        result = await get_entity_by_url("https://example.com/page#section")

    assert result is entity
    backend.get_entity_by_platform.assert_awaited_once_with("web", "https://example.com/page")


@pytest.mark.asyncio
async def test_get_entity_by_url_falls_back_to_web_metadata_urls() -> None:
    from agentgraph.connectors.base import SourceReference
    from agentgraph.graph.query import get_entity_by_url

    entity = _entity(platform="web", title="Redirected Page")
    backend = _mock_backend(
        get_entity_by_platform=AsyncMock(return_value=None),
        query_by_filter=AsyncMock(side_effect=[[], [entity]]),
    )
    set_backend(backend)

    class FakeWebConnector:
        def resolve_url(self, url: str) -> SourceReference | None:
            return SourceReference("web", "document", "https://example.com/final")

        def entity_url(self, platform_entity_id: str) -> str:
            return platform_entity_id

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.server.router.classify_url", return_value=None),
        patch("agentgraph.connectors.registry.get_connector", return_value=FakeWebConnector()),
    ):
        result = await get_entity_by_url("https://example.com/original")

    assert result is entity
    backend.query_by_filter.assert_any_await(
        "Document",
        {"platform": "web", "url": "https://example.com/original"},
        1,
        "updated_at",
        None,
        None,
    )
    backend.query_by_filter.assert_any_await(
        "Document",
        {"platform": "web", "final_url": "https://example.com/original"},
        1,
        "updated_at",
        None,
        None,
    )


@pytest.mark.asyncio
async def test_get_entity_by_url_missing_does_not_fetch_or_upsert() -> None:
    from agentgraph.connectors.base import SourceReference
    from agentgraph.graph.query import get_entity_by_url

    backend = _mock_backend(get_entity_by_platform=AsyncMock(return_value=None))
    set_backend(backend)
    fetch = AsyncMock()

    class FakeWebConnector:
        async def fetch(self, *_args: object) -> None:
            await fetch()

        def resolve_url(self, url: str) -> SourceReference | None:
            return SourceReference("web", "document", url)

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.server.router.classify_url", return_value=None),
        patch("agentgraph.connectors.registry.get_connector", return_value=FakeWebConnector()),
        patch("agentgraph.graph.upsert.upsert_batch", new=AsyncMock()) as upsert_batch,
    ):
        result = await get_entity_by_url("https://example.com/missing")

    assert result is None
    fetch.assert_not_awaited()
    upsert_batch.assert_not_awaited()


# ---------------------------------------------------------------------------
# get_edges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_edges_returns_edges() -> None:
    from agentgraph.graph.query import get_edges

    eid = str(uuid4())
    edge = _edge(source_entity_id=eid)
    backend = _mock_backend(get_edges=AsyncMock(return_value=[edge]))
    set_backend(backend)

    edges = await get_edges(eid, direction="out")
    assert len(edges) == 1
    assert edges[0]["edge_type"] == "authored"


# ---------------------------------------------------------------------------
# bookmark_entity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bookmark_entity_resolves_id_and_sets_bookmark() -> None:
    from agentgraph.graph.bookmark import bookmark_entity

    entity = _entity(title="Target")
    updated = dict(entity)
    updated["bookmarked"] = True
    set_bookmarked = AsyncMock(return_value=updated)
    backend = _mock_backend(
        get_entities_by_id_prefix=AsyncMock(return_value=[entity]),
        set_entity_bookmarked=set_bookmarked,
    )
    set_backend(backend)

    result = await bookmark_entity(entity["id"][:8])

    assert result["bookmarked"] is True
    set_bookmarked.assert_awaited_once_with(entity["id"], True)


@pytest.mark.asyncio
async def test_set_entity_bookmark_can_clear_bookmark() -> None:
    from agentgraph.graph.bookmark import set_entity_bookmark

    entity = _entity(title="Target")
    entity["bookmarked"] = True
    updated = dict(entity)
    updated["bookmarked"] = False
    set_bookmarked = AsyncMock(return_value=updated)
    backend = _mock_backend(
        get_entities_by_id_prefix=AsyncMock(return_value=[entity]),
        set_entity_bookmarked=set_bookmarked,
    )
    set_backend(backend)

    result = await set_entity_bookmark(entity["id"][:8], False)

    assert result["bookmarked"] is False
    set_bookmarked.assert_awaited_once_with(entity["id"], False)


@pytest.mark.asyncio
async def test_cli_bookmark_can_clear_bookmark() -> None:
    from agentgraph.server.cli_api import cli_bookmark

    fake_result = _entity(title="Target")
    fake_result["bookmarked"] = False

    with patch(
        "agentgraph.graph.bookmark.set_entity_bookmark",
        new=AsyncMock(return_value=fake_result),
    ) as set_bookmark:
        result = await cli_bookmark(target=None, entity_id="abc123", bookmarked=False)

    assert result["bookmarked"] is False
    set_bookmark.assert_awaited_once_with("abc123", False)


@pytest.mark.asyncio
async def test_cli_download_downloads_entity() -> None:
    from agentgraph.server.cli_api import cli_download

    fake_result: dict[str, Any] = {"path": "/tmp/file.pdf", "bytes": 7, "filename": "file.pdf"}

    with patch(
        "agentgraph.graph.download.download_entity",
        new=AsyncMock(return_value=fake_result),
    ) as download_entity:
        result = await cli_download(entity_id="abc123", output_path="/tmp")

    assert result == fake_result
    download_entity.assert_awaited_once_with("abc123", "/tmp")


@pytest.mark.asyncio
async def test_bookmark_entity_missing_raises_value_error() -> None:
    from agentgraph.graph.bookmark import bookmark_entity

    backend = _mock_backend(get_entities_by_id_prefix=AsyncMock(return_value=[]))
    set_backend(backend)

    with pytest.raises(ValueError, match="not found"):
        await bookmark_entity("missing")


@pytest.mark.asyncio
async def test_bookmark_url_uses_owning_connector() -> None:
    from agentgraph.connectors.base import EntityBatch, SourceReference
    from agentgraph.graph.bookmark import bookmark_target

    entity = _entity(platform="gdocs", title="Fetched Doc")
    updated = dict(entity)
    updated["bookmarked"] = True
    backend = _mock_backend(
        get_entity_by_platform=AsyncMock(return_value=entity),
        set_entity_bookmarked=AsyncMock(return_value=updated),
    )
    set_backend(backend)

    class FakeConnector:
        async def fetch(
            self,
            resource_type: str,
            resource_id: str,
        ) -> EntityBatch:
            assert resource_type == "document"
            assert resource_id == "doc-1"
            return EntityBatch()

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_connector", return_value=FakeConnector()),
        patch(
            "agentgraph.server.router.classify_url",
            return_value=SourceReference("gdocs", "document", "doc-1"),
        ),
    ):
        result = await bookmark_target("https://docs.google.com/document/d/doc-1/edit")

    assert result["bookmarked"] is True
    backend.set_entity_bookmarked.assert_awaited_once_with(entity["id"], True)


@pytest.mark.asyncio
async def test_bookmark_url_falls_back_to_web_connector() -> None:
    from agentgraph.connectors.base import EntityBatch, EntityRecord
    from agentgraph.graph.bookmark import bookmark_target

    entity = _entity(platform="web", title="Fetched Page")
    updated = dict(entity)
    updated["bookmarked"] = True
    backend = _mock_backend(
        get_entity_by_platform=AsyncMock(return_value=entity),
        set_entity_bookmarked=AsyncMock(return_value=updated),
    )
    set_backend(backend)

    class FakeWebConnector:
        async def fetch(
            self,
            resource_type: str,
            resource_id: str,
        ) -> EntityBatch:
            assert resource_type == "document"
            assert resource_id == "https://example.com/page"
            return EntityBatch(
                entities=[
                    EntityRecord(
                        entity_type="Document",
                        platform="web",
                        platform_entity_id="https://example.com/page",
                        title="Fetched Page",
                        content="Body",
                    )
                ]
            )

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_connector", return_value=FakeWebConnector()),
        patch("agentgraph.server.router.classify_url", return_value=None),
        patch("agentgraph.graph.upsert.upsert_batch", new=AsyncMock()),
    ):
        result = await bookmark_target("https://example.com/page")

    assert result["bookmarked"] is True
    backend.set_entity_bookmarked.assert_awaited_once_with(entity["id"], True)


# ---------------------------------------------------------------------------
# delete_entity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_entity_resolves_id_and_deletes() -> None:
    from agentgraph.graph.delete import delete_entity

    entity = _entity(title="Target")
    backend = _mock_backend(
        get_entities_by_id_prefix=AsyncMock(return_value=[entity]),
        delete_entity=AsyncMock(return_value=entity),
    )
    set_backend(backend)

    result = await delete_entity(entity["id"][:8])

    assert result["deleted"] is True
    assert result["entity"]["id"] == entity["id"]
    backend.delete_entity.assert_awaited_once_with(entity["id"])


@pytest.mark.asyncio
async def test_delete_entity_missing_raises_value_error() -> None:
    from agentgraph.graph.delete import delete_entity

    backend = _mock_backend(get_entities_by_id_prefix=AsyncMock(return_value=[]))
    set_backend(backend)

    with pytest.raises(ValueError, match="not found"):
        await delete_entity("missing")


@pytest.mark.asyncio
async def test_cli_delete_deletes_entity() -> None:
    from agentgraph.server.cli_api import cli_delete

    fake_result = {"deleted": True, "entity": _entity(title="Target")}

    with patch(
        "agentgraph.graph.delete.delete_entity",
        new=AsyncMock(return_value=fake_result),
    ) as delete_entity:
        result = await cli_delete(target="abc123")

    assert result["deleted"] is True
    delete_entity.assert_awaited_once_with("abc123")


@pytest.mark.asyncio
async def test_cli_search_summarizes_long_content() -> None:
    from agentgraph.server.cli_api import cli_search

    entity = _entity(content="x" * 700)

    with patch("agentgraph.server.cli_api.search_entities", new=AsyncMock(return_value=[entity])):
        result = await cli_search(q="x")

    assert len(result[0]["content"]) == 500
    assert result[0]["content_truncated"] is True


@pytest.mark.asyncio
async def test_cli_query_summarizes_long_content() -> None:
    from agentgraph.server.cli_api import cli_query

    entity = _entity(content="x" * 700)

    with patch("agentgraph.server.cli_api.query_by_filter", new=AsyncMock(return_value=[entity])):
        result = await cli_query(entity_type="Message", filter=[])

    assert len(result[0]["content"]) == 500
    assert result[0]["content_truncated"] is True


# ---------------------------------------------------------------------------
# MCP tool wrappers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_search_entities_tool_returns_json() -> None:
    from agentgraph.mcp.server import search_entities_tool

    with patch("agentgraph.mcp.server.search_entities", new=AsyncMock(return_value=[])):
        result = await search_entities_tool("test")

    parsed = json.loads(result)
    assert isinstance(parsed, list)


@pytest.mark.asyncio
async def test_mcp_search_entities_tool_skips_connector_enrichment_by_default() -> None:
    from agentgraph.mcp.server import search_entities_tool

    entity = _entity(platform="example")

    class FakeConnector:
        async def enrich_results(self, entities: list[dict[str, Any]]) -> None:
            entities[0]["metadata"]["enriched"] = True

    with (
        patch("agentgraph.mcp.server.search_entities", new=AsyncMock(return_value=[entity])),
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_connector", return_value=FakeConnector()),
    ):
        result = await search_entities_tool("test")

    parsed = json.loads(result)
    assert "enriched" not in parsed[0]["metadata"]


@pytest.mark.asyncio
async def test_mcp_search_entities_tool_enriches_results_via_connector_when_refreshed() -> None:
    from agentgraph.mcp.server import search_entities_tool

    entity = _entity(platform="example")

    class FakeConnector:
        async def enrich_results(self, entities: list[dict[str, Any]]) -> None:
            entities[0]["metadata"]["enriched"] = True

    with (
        patch("agentgraph.mcp.server.search_entities", new=AsyncMock(return_value=[entity])),
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_connector", return_value=FakeConnector()),
    ):
        result = await search_entities_tool("test", refresh=True)

    parsed = json.loads(result)
    assert parsed[0]["metadata"]["enriched"] is True


@pytest.mark.asyncio
async def test_mcp_get_entity_tool_not_found() -> None:
    from agentgraph.mcp.server import get_entity_tool

    eid = str(uuid4())
    with patch("agentgraph.mcp.server.get_entity", new=AsyncMock(return_value=None)):
        result = await get_entity_tool(eid)

    parsed = json.loads(result)
    assert "error" in parsed


@pytest.mark.asyncio
async def test_mcp_get_entity_tool_found() -> None:
    from agentgraph.mcp.server import get_entity_tool

    eid = str(uuid4())
    fake_entity = _entity(title="My Doc")
    fake_entity["id"] = eid
    with patch("agentgraph.mcp.server.get_entity", new=AsyncMock(return_value=fake_entity)):
        result = await get_entity_tool(eid)

    parsed = json.loads(result)
    assert parsed["title"] == "My Doc"


@pytest.mark.asyncio
async def test_mcp_get_entity_tool_url_found() -> None:
    from agentgraph.mcp.server import get_entity_tool

    fake_entity = _entity(platform="web", title="Web Page")
    with patch("agentgraph.graph.query.get_entity_by_url", new=AsyncMock(return_value=fake_entity)):
        result = await get_entity_tool("https://example.com/page")

    parsed = json.loads(result)
    assert parsed["title"] == "Web Page"


@pytest.mark.asyncio
async def test_mcp_get_entity_tool_url_not_found() -> None:
    from agentgraph.mcp.server import get_entity_tool

    with patch("agentgraph.graph.query.get_entity_by_url", new=AsyncMock(return_value=None)):
        result = await get_entity_tool("https://example.com/missing")

    parsed = json.loads(result)
    assert "error" in parsed


@pytest.mark.asyncio
async def test_mcp_traverse_caps_depth() -> None:
    from agentgraph.mcp.server import traverse_graph_tool

    captured: dict[str, Any] = {}

    async def fake_traverse(entity_id: str, max_depth: int) -> dict[str, Any]:
        captured["depth"] = max_depth
        return {"nodes": [], "edges": []}

    with patch("agentgraph.mcp.server.traverse_graph", new=fake_traverse):
        await traverse_graph_tool(str(uuid4()), max_depth=99)

    assert captured["depth"] == 4  # capped at 4


@pytest.mark.asyncio
async def test_mcp_traverse_allows_depth_zero() -> None:
    from agentgraph.mcp.server import traverse_graph_tool

    captured: dict[str, Any] = {}

    async def fake_traverse(entity_id: str, max_depth: int) -> dict[str, Any]:
        captured["depth"] = max_depth
        return {"nodes": [], "edges": []}

    with patch("agentgraph.mcp.server.traverse_graph", new=fake_traverse):
        await traverse_graph_tool(str(uuid4()), max_depth=0)

    assert captured["depth"] == 0


@pytest.mark.asyncio
async def test_mcp_query_by_filter_tool() -> None:
    from agentgraph.mcp.server import query_by_filter_tool

    with patch("agentgraph.mcp.server.query_by_filter", new=AsyncMock(return_value=[])):
        result = await query_by_filter_tool("Message", filters={"channel_id": "C123"})

    parsed = json.loads(result)
    assert isinstance(parsed, list)


@pytest.mark.asyncio
async def test_mcp_query_by_filter_tool_truncates_long_content() -> None:
    from agentgraph.mcp.server import query_by_filter_tool

    entity = _entity(content="x" * 700)

    with (
        patch("agentgraph.mcp.server.query_by_filter", new=AsyncMock(return_value=[entity])),
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_connector", return_value=None),
    ):
        result = await query_by_filter_tool("Message")

    parsed = json.loads(result)
    assert len(parsed[0]["content"]) == 501
    assert parsed[0]["content_truncated"] is True


@pytest.mark.asyncio
async def test_mcp_download_entity_tool() -> None:
    from agentgraph.mcp.server import download_entity_tool

    fake_result = {"path": "/tmp/file.pdf", "bytes": 7, "filename": "file.pdf"}
    with patch(
        "agentgraph.graph.download.download_entity", new=AsyncMock(return_value=fake_result)
    ):
        result = await download_entity_tool("abc123", "/tmp")

    assert json.loads(result) == fake_result


@pytest.mark.asyncio
async def test_mcp_bookmark_entity_tool() -> None:
    from agentgraph.mcp.server import bookmark_entity_tool

    fake_result = _entity(title="My Doc")
    fake_result["bookmarked"] = True
    with patch(
        "agentgraph.graph.bookmark.bookmark_target", new=AsyncMock(return_value=fake_result)
    ):
        result = await bookmark_entity_tool("abc123")

    parsed = json.loads(result)
    assert parsed["bookmarked"] is True


@pytest.mark.asyncio
async def test_mcp_bookmark_entity_tool_can_remove_bookmark() -> None:
    from agentgraph.mcp.server import bookmark_entity_tool

    fake_result = _entity(title="My Doc")
    fake_result["bookmarked"] = False
    with patch(
        "agentgraph.graph.bookmark.set_entity_bookmark", new=AsyncMock(return_value=fake_result)
    ) as set_bookmark:
        result = await bookmark_entity_tool("abc123", bookmarked=False)

    parsed = json.loads(result)
    assert parsed["bookmarked"] is False
    set_bookmark.assert_awaited_once_with("abc123", False)


@pytest.mark.asyncio
async def test_mcp_delete_entity_tool() -> None:
    from agentgraph.mcp.server import delete_entity_tool

    fake_result = {"deleted": True, "entity": _entity(title="My Doc")}
    with patch("agentgraph.graph.delete.delete_entity", new=AsyncMock(return_value=fake_result)):
        result = await delete_entity_tool("abc123")

    parsed = json.loads(result)
    assert parsed["deleted"] is True


@pytest.mark.asyncio
async def test_mcp_list_auth_providers_tool_returns_json() -> None:
    from agentgraph.mcp.server import list_auth_providers_tool

    fake_items = [
        {
            "provider": "google",
            "description": "Shared auth for gdocs, gdrive",
            "connectors": ["gdocs", "gdrive"],
            "shared": True,
            "auth_status": "ok",
            "auth_detail": "1 account(s)",
            "accounts": [],
        }
    ]

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_all_connectors", return_value=[]),
        patch(
            "agentgraph.connectors.status.auth_provider_status_items",
            new=AsyncMock(return_value=fake_items),
        ),
    ):
        result = await list_auth_providers_tool()

    assert json.loads(result) == fake_items


@pytest.mark.asyncio
async def test_mcp_remove_auth_provider_tool_removes_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentgraph.auth.credentials import load_platform, save_platform
    from agentgraph.mcp.server import remove_auth_provider_tool

    creds_file = tmp_path / "credentials.json"
    monkeypatch.setattr("agentgraph.auth.credentials.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("agentgraph.auth.credentials.CREDENTIALS_FILE", creds_file)
    save_platform("slack", {"xoxc_token": "xoxc-test", "d_cookie": "cookie"})

    result = await remove_auth_provider_tool("slack")

    parsed = json.loads(result)
    assert parsed == {"provider": "slack", "removed": True}
    assert load_platform("slack") is None


@pytest.mark.asyncio
async def test_mcp_list_connectors_tool_returns_json() -> None:
    from agentgraph.mcp.server import list_connectors_tool

    fake_items = [
        {
            "source": "gdocs",
            "description": "Google Docs",
            "auth_provider": "google",
            "shared_auth": True,
            "auth_status": "ok",
            "auth_detail": "1 account(s)",
            "accounts": [],
            "account_count": 1,
            "url_patterns": [],
            "polls": False,
            "poll_interval_seconds": None,
            "poll_delegates": [],
            "polled_by": ["gdrive"],
            "sync": "via gdrive poll",
            "last_synced_at": None,
            "last_sync": "never",
        }
    ]
    set_backend(_mock_backend(get_platform_last_synced_at=AsyncMock(return_value=None)))

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_all_connectors", return_value=[]),
        patch(
            "agentgraph.connectors.status.connector_status_items",
            new=AsyncMock(return_value=fake_items),
        ),
    ):
        result = await list_connectors_tool()

    assert json.loads(result) == fake_items


@pytest.mark.asyncio
async def test_mcp_install_skill_tool_installs_to_user_agents_skills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentgraph.mcp.server import install_skill_tool

    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    result = await install_skill_tool()

    parsed = json.loads(result)
    assert parsed["skill"] == "graph"
    assert parsed["target"] == "user"
    assert parsed["overwritten"] is False
    assert (home / ".agents" / "skills" / "graph" / "SKILL.md").is_file()


@pytest.mark.asyncio
async def test_mcp_install_skill_tool_reports_invalid_target() -> None:
    from agentgraph.mcp.server import install_skill_tool

    result = await install_skill_tool(target="elsewhere")

    parsed = json.loads(result)
    assert "error" in parsed


@pytest.mark.asyncio
async def test_mcp_poll_connectors_tool_starts_poll_tasks() -> None:
    from agentgraph.mcp.server import poll_connectors_tool

    class PollingConnector:
        source = "rss"
        poll_interval = object()

    class PassiveConnector:
        source = "gdocs"
        poll_interval = None

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch(
            "agentgraph.connectors.registry.get_all_connectors",
            return_value=[PollingConnector(), PassiveConnector()],
        ),
        patch(
            "agentgraph.server.sync.schedule_poll_connector",
            new=AsyncMock(return_value={"source": "rss", "status": "queued", "reason": None}),
        ) as schedule_poll,
    ):
        result = await poll_connectors_tool()

    assert json.loads(result) == {"polled": ["rss"], "already_running": [], "skipped": []}
    schedule_poll.assert_called_once()


@pytest.mark.asyncio
async def test_mcp_poll_connectors_tool_uses_source_connector_lookup() -> None:
    from agentgraph.mcp.server import poll_connectors_tool

    class PollingConnector:
        source = "rss"
        poll_interval = object()

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch(
            "agentgraph.connectors.registry.get_connector", return_value=PollingConnector()
        ) as get_connector,
        patch("agentgraph.connectors.registry.get_all_connectors") as get_all_connectors,
        patch(
            "agentgraph.server.sync.schedule_poll_connector",
            new=AsyncMock(return_value={"source": "rss", "status": "queued", "reason": None}),
        ) as schedule_poll,
    ):
        result = await poll_connectors_tool("rss")

    assert json.loads(result) == {"polled": ["rss"], "already_running": [], "skipped": []}
    get_connector.assert_called_once_with("rss")
    get_all_connectors.assert_not_called()
    schedule_poll.assert_called_once()


@pytest.mark.asyncio
async def test_mcp_poll_connectors_tool_reports_already_running() -> None:
    from agentgraph.mcp.server import poll_connectors_tool

    class PollingConnector:
        source = "rss"
        poll_interval = object()

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_all_connectors", return_value=[PollingConnector()]),
        patch(
            "agentgraph.server.sync.schedule_poll_connector",
            new=AsyncMock(
                return_value={"source": "rss", "status": "already_running", "reason": None}
            ),
        ),
    ):
        result = await poll_connectors_tool()

    assert json.loads(result) == {"polled": [], "already_running": ["rss"], "skipped": []}


@pytest.mark.asyncio
async def test_mcp_poll_connectors_tool_reports_skipped_auth() -> None:
    from agentgraph.mcp.server import poll_connectors_tool

    class PollingConnector:
        source = "gmail"
        poll_interval = object()

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_all_connectors", return_value=[PollingConnector()]),
        patch(
            "agentgraph.server.sync.schedule_poll_connector",
            new=AsyncMock(
                return_value={
                    "source": "gmail",
                    "status": "skipped",
                    "reason": "authentication invalid: token expired",
                }
            ),
        ),
    ):
        result = await poll_connectors_tool()

    assert json.loads(result) == {
        "polled": [],
        "already_running": [],
        "skipped": [{"source": "gmail", "reason": "authentication invalid: token expired"}],
    }


@pytest.mark.asyncio
async def test_mcp_poll_connectors_tool_reports_unknown_source() -> None:
    from agentgraph.mcp.server import poll_connectors_tool

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_connector", return_value=None),
    ):
        result = await poll_connectors_tool("missing")

    parsed = json.loads(result)
    assert "error" in parsed


@pytest.mark.asyncio
async def test_mcp_ingest_connector_tool_starts_ingest_task() -> None:
    from agentgraph.mcp.server import ingest_connector_tool

    class Connector:
        source = "rss"

    created: list[Any] = []

    def fake_create_task(coro: Any) -> MagicMock:
        created.append(coro)
        coro.close()
        return MagicMock()

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_connector", return_value=Connector()),
        patch("agentgraph.server.sync.run_ingest", new=AsyncMock()),
        patch("agentgraph.mcp.server.asyncio.create_task", side_effect=fake_create_task),
    ):
        result = await ingest_connector_tool("rss")

    assert json.loads(result) == {"source": "rss", "status": "started"}
    assert len(created) == 1


@pytest.mark.asyncio
async def test_mcp_ingest_connector_tool_reports_unknown_source() -> None:
    from agentgraph.mcp.server import ingest_connector_tool

    with (
        patch("agentgraph.connectors.registry.bootstrap"),
        patch("agentgraph.connectors.registry.get_connector", return_value=None),
    ):
        result = await ingest_connector_tool("missing")

    parsed = json.loads(result)
    assert "error" in parsed
