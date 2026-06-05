"""URL routing through connector-owned resolvers."""

from __future__ import annotations

import re

from agentgraph.connectors.base import SourceReference

# U+200B zero-width space, U+200C/D/E/F directional marks, U+00AD soft hyphen, U+FEFF BOM
_INVISIBLE_CHARS_RE = re.compile(
    "[­​‌‍‎‏﻿]+"
)


def normalise_url_for_matching(url: str) -> str:
    """Strip invisible characters and punctuation commonly wrapping URLs in prose."""
    return _INVISIBLE_CHARS_RE.sub("", url).rstrip(".,)>\"'")


def classify_url(url: str) -> SourceReference | None:
    """Return a SourceReference for a connector-owned URL, or None."""
    from agentgraph.connectors.registry import bootstrap, get_all_connectors

    normalised_url = normalise_url_for_matching(url)
    bootstrap()
    for connector in get_all_connectors():
        ref = connector.resolve_url(normalised_url)
        if ref is not None:
            return ref
    return None
