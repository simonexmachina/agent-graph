"""Tests for Chrome-style match-pattern matching shared with the browser extension."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentgraph.connectors.match_patterns import matches_pattern

_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "url_match_cases.json").read_text(encoding="utf-8")
)
_CASES = _FIXTURE["cases"]


@pytest.mark.parametrize(
    ("url", "pattern", "expected"),
    [
        pytest.param(case["url"], case["pattern"], case["expected"], id=case["name"])
        for case in _CASES
    ],
)
def test_shared_match_pattern_vectors(url: str, pattern: str, expected: bool) -> None:
    """The same vectors run against `matchesPattern` in extension/test/observation.test.mjs."""
    assert matches_pattern(url, pattern) is expected


def test_pattern_without_a_scheme_is_compared_exactly() -> None:
    assert matches_pattern("example.com/page", "example.com/page") is True
    assert matches_pattern("https://example.com/page", "example.com/page") is False
