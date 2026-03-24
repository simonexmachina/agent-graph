"""CLI query commands — thin wrappers over the graph query layer."""

from __future__ import annotations


def cmd_search(query: str, entity_types: list[str], limit: int, as_json: bool) -> None:
    raise NotImplementedError


def cmd_get(entity_id: str, as_json: bool) -> None:
    raise NotImplementedError


def cmd_edges(
    entity_id: str, edge_type: str | None, direction: str, as_json: bool
) -> None:
    raise NotImplementedError


def cmd_traverse(entity_id: str, max_depth: int, as_json: bool) -> None:
    raise NotImplementedError


def cmd_query(
    entity_type: str, filters: dict[str, str], limit: int, as_json: bool
) -> None:
    raise NotImplementedError
