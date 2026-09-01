"""Display fields derived from an entity, for callers that render it.

These are pure functions of an entity's own fields, so they could in principle live in
the client. They stay server-side because ``display_name`` is a sort key: the browse
endpoint orders by it *before* paginating, and a client-computed field could only be
sorted within a page.

Requested explicitly via ``?include=display`` — responses are otherwise the plain graph
shape, which is what keeps CLI output identical across transports.
"""

from __future__ import annotations

import re
from typing import Any, cast

_WHITESPACE_RE = re.compile(r"\s+")

_MESSAGE_LABEL_LIMIT = 80


def _normalise_display_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = _WHITESPACE_RE.sub(" ", value).strip()
    return text or None


def entity_display_name(entity: dict[str, Any]) -> str:
    """Best human-readable name for an entity, falling back through its fields."""
    metadata = entity.get("metadata")
    metadata_dict: dict[str, Any] = cast("dict[str, Any]", metadata) if isinstance(metadata, dict) else {}
    candidates: tuple[object, ...] = (
        entity.get("title"),
        metadata_dict.get("display_name"),
        metadata_dict.get("canonical_email"),
        entity.get("content"),
        entity.get("platform_entity_id"),
        entity.get("id"),
    )
    for candidate in candidates:
        text = _normalise_display_text(candidate)
        if text:
            return text
    return "Untitled"


def truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(limit - 1, 0)].rstrip() + "…"


def entity_label(entity: dict[str, Any]) -> str:
    """Display name, shortened for Messages whose content is the name."""
    display_name = entity_display_name(entity)
    if entity.get("entity_type") == "Message":
        return truncate_text(display_name, _MESSAGE_LABEL_LIMIT)
    return display_name


def with_display_name(entity: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(entity)
    enriched["display_name"] = entity_display_name(entity)
    enriched["viewer_label"] = entity_label(entity)
    return enriched


def with_display_names(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [with_display_name(entity) for entity in entities]
