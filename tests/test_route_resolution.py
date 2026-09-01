"""Route declaration order must keep specific paths ahead of the ref catch-all.

Entity refs are UUIDs, ``platform/id`` paths, or http URLs, so the entity routes match
with a path converter. A path converter is greedy: if ``/api/entities/{ref:path}`` were
declared before ``/api/entities/search`` or the ``/edges`` suffix routes, it would
swallow them and a lookup for "search" would silently shadow the search endpoint.
Nothing else in the suite would fail, so this pins the ordering directly.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentgraph.server.app import app

# (path, expected handler name)
CASES = [
    ("/api/entities/search", "search_entities"),
    ("/api/capabilities", "capabilities"),
    ("/api/entities/22c57772-78cb-4234-ada7-36730b26e52c", "get_entity"),
    ("/api/entities/slack/TDEMO/CATLAS", "get_entity"),
    ("/api/entities/22c57772-78cb-4234-ada7-36730b26e52c/edges", "entity_edges"),
    ("/api/entities/slack/TDEMO/CATLAS/edges", "entity_edges"),
    ("/api/graph/nodes", "browse_nodes"),
    ("/api/graph/traverse/slack/TDEMO/CATLAS", "traverse"),
]


def _resolve(path: str, method: str = "GET") -> str | None:
    """Return the name of the endpoint Starlette would dispatch this path to."""
    from starlette.routing import Match

    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
    }
    for route in app.routes:
        match, _ = route.matches(scope)
        if match is Match.FULL:
            endpoint = getattr(route, "endpoint", None)
            return getattr(endpoint, "__name__", None)
    return None


@pytest.mark.parametrize(("path", "expected"), CASES)
def test_path_resolves_to_expected_handler(path: str, expected: str) -> None:
    assert _resolve(path) == expected


def test_delete_and_get_on_an_entity_reach_different_handlers() -> None:
    ref = "/api/entities/22c57772-78cb-4234-ada7-36730b26e52c"

    assert _resolve(ref, "GET") == "get_entity"
    assert _resolve(ref, "DELETE") == "delete_entity"


def test_entity_subresource_suffixes_are_declared_before_the_catch_all() -> None:
    """Guards the ordering itself, independent of matching behaviour."""
    paths = [getattr(route, "path", "") for route in app.routes]
    catch_all = paths.index("/api/entities/{ref:path}")

    for suffix in ("/edges", "/bookmark", "/fetch", "/download"):
        route = f"/api/entities/{{ref:path}}{suffix}"
        assert paths.index(route) < catch_all, f"{route} must precede the catch-all"

    for literal in ("/api/entities/search", "/api/entities/filter"):
        assert paths.index(literal) < catch_all, f"{literal} must precede the catch-all"
