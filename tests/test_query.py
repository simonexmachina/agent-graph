"""Unit tests for the graph query layer and MCP tools (mocked backend)."""

from __future__ import annotations

import json
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
        "set_entity_bookmarked": AsyncMock(return_value=_entity(title="Bookmarked Doc")),
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

    with patch("agentgraph.graph.query.encode", return_value=[0.1] * 384):
        results = await search_entities("test query", limit=5)

    assert len(results) == 2
    assert results[0]["entity_type"] == "Document"


@pytest.mark.asyncio
async def test_search_entities_empty_results() -> None:
    from agentgraph.graph.query import search_entities

    backend = _mock_backend(search_entities=AsyncMock(return_value=[]))
    set_backend(backend)

    with patch("agentgraph.graph.query.encode", return_value=[0.0] * 384):
        results = await search_entities("empty query")

    assert results == []


@pytest.mark.asyncio
async def test_search_entities_passes_platform_to_backend() -> None:
    from agentgraph.graph.query import search_entities

    mock_search = AsyncMock(return_value=[])
    backend = _mock_backend(search_entities=mock_search)
    set_backend(backend)

    with patch("agentgraph.graph.query.encode", return_value=[0.1] * 384):
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

    with patch("agentgraph.graph.query.encode", return_value=[0.1] * 384):
        await search_entities("anything")

    mock_search.assert_called_once()
    _, kwargs = mock_search.call_args
    assert kwargs.get("platform") is None


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

    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch(
             "agentgraph.server.router.classify_url",
             return_value=SourceReference("gdocs", "document", "doc-1"),
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

    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.server.router.classify_url", return_value=None), \
         patch("agentgraph.connectors.registry.get_connector", return_value=FakeWebConnector()):
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

    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.server.router.classify_url", return_value=None), \
         patch("agentgraph.connectors.registry.get_connector", return_value=FakeWebConnector()):
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

    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.server.router.classify_url", return_value=None), \
         patch("agentgraph.connectors.registry.get_connector", return_value=FakeWebConnector()), \
         patch("agentgraph.graph.upsert.upsert_batch", new=AsyncMock()) as upsert_batch:
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

    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.connectors.registry.get_connector", return_value=FakeConnector()), \
         patch(
             "agentgraph.server.router.classify_url",
             return_value=SourceReference("gdocs", "document", "doc-1"),
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
            return EntityBatch(entities=[
                EntityRecord(
                    entity_type="Document",
                    platform="web",
                    platform_entity_id="https://example.com/page",
                    title="Fetched Page",
                    content="Body",
                )
            ])

    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.connectors.registry.get_connector", return_value=FakeWebConnector()), \
         patch("agentgraph.server.router.classify_url", return_value=None), \
         patch("agentgraph.graph.upsert.upsert_batch", new=AsyncMock()):
        result = await bookmark_target("https://example.com/page")

    assert result["bookmarked"] is True
    backend.set_entity_bookmarked.assert_awaited_once_with(entity["id"], True)


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
async def test_mcp_search_entities_tool_enriches_results_via_connector() -> None:
    from agentgraph.mcp.server import search_entities_tool

    entity = _entity(platform="example")

    class FakeConnector:
        async def enrich_results(self, entities: list[dict[str, Any]]) -> None:
            entities[0]["metadata"]["enriched"] = True

    with patch("agentgraph.mcp.server.search_entities", new=AsyncMock(return_value=[entity])), \
         patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.connectors.registry.get_connector", return_value=FakeConnector()):
        result = await search_entities_tool("test")

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
async def test_mcp_query_by_filter_tool() -> None:
    from agentgraph.mcp.server import query_by_filter_tool

    with patch("agentgraph.mcp.server.query_by_filter", new=AsyncMock(return_value=[])):
        result = await query_by_filter_tool("Message", filters={"channel_id": "C123"})

    parsed = json.loads(result)
    assert isinstance(parsed, list)


@pytest.mark.asyncio
async def test_mcp_download_entity_tool() -> None:
    from agentgraph.mcp.server import download_entity_tool

    fake_result = {"path": "/tmp/file.pdf", "bytes": 7, "filename": "file.pdf"}
    with patch("agentgraph.graph.download.download_entity", new=AsyncMock(return_value=fake_result)):
        result = await download_entity_tool("abc123", "/tmp")

    assert json.loads(result) == fake_result


@pytest.mark.asyncio
async def test_mcp_bookmark_entity_tool() -> None:
    from agentgraph.mcp.server import bookmark_entity_tool

    fake_result = _entity(title="My Doc")
    fake_result["bookmarked"] = True
    with patch("agentgraph.graph.bookmark.bookmark_target", new=AsyncMock(return_value=fake_result)):
        result = await bookmark_entity_tool("abc123")

    parsed = json.loads(result)
    assert parsed["bookmarked"] is True


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

    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.connectors.registry.get_all_connectors", return_value=[]), \
         patch("agentgraph.connectors.status.auth_provider_status_items", new=AsyncMock(return_value=fake_items)):
        result = await list_auth_providers_tool()

    assert json.loads(result) == fake_items


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

    with patch("agentgraph.connectors.registry.bootstrap"), \
         patch("agentgraph.connectors.registry.get_all_connectors", return_value=[]), \
         patch("agentgraph.connectors.status.connector_status_items", new=AsyncMock(return_value=fake_items)):
        result = await list_connectors_tool()

    assert json.loads(result) == fake_items
