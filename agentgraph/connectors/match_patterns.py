"""Chrome-style match-pattern matching for connector `url_patterns`.

Mirrors `matchesPattern` in `extension/lib/observation.ts` so the browser
extension and the server agree on which URLs a connector claims.
`tests/fixtures/url_match_cases.json` holds the shared test vectors.
"""

from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": "80", "https": "443"}


def matches_pattern(url: str, pattern: str) -> bool:
    """Return True when `url` matches a `<scheme>://<host>[:<port>]/<path>` pattern.

    The host may begin with `*.` to cover a domain and its subdomains, or be a
    bare `*`. In the path, `*` matches any span of characters — including `/`,
    unlike a filesystem glob — and is matched against the path plus query, so
    the fragment is ignored. A pattern without a port matches any port; one with
    a port requires it, with a scheme's default port treated as absent. A
    pattern without a scheme is compared to the URL exactly.
    """
    parts = _split_pattern(pattern)
    if parts is None:
        return url == pattern

    scheme_pattern, host_pattern, port_pattern, path_pattern = parts
    target = urlsplit(url)
    if not target.scheme:
        return False
    try:
        hostname = target.hostname or ""
        port = target.port
    except ValueError:
        return False

    if scheme_pattern != "*" and scheme_pattern != target.scheme:
        return False
    if not _port_matches(target.scheme, port, port_pattern):
        return False
    if not _host_matches(hostname, host_pattern):
        return False

    path = target.path or "/"
    query = f"?{target.query}" if target.query else ""
    return _path_regexp(path_pattern).match(f"{path}{query}") is not None


def _split_pattern(pattern: str) -> tuple[str, str, str, str] | None:
    scheme, separator, rest = pattern.partition("://")
    if not separator:
        return None
    authority, slash, path = rest.partition("/")
    host, port = _split_authority(authority)
    return scheme, host, port, f"{slash}{path}" if slash else "/*"


def _split_authority(authority: str) -> tuple[str, str]:
    """Peel a trailing `:<digits>` off the host, leaving `*` and IPv6-ish hosts intact."""
    host, separator, port = authority.rpartition(":")
    if not separator or not port.isdigit():
        return authority, ""
    return host, port


def _port_matches(scheme: str, target_port: int | None, port_pattern: str) -> bool:
    # A pattern without a port matches any port, as Chrome match patterns do.
    if not port_pattern:
        return True
    return _effective_port(scheme, port_pattern) == _effective_port(
        scheme, "" if target_port is None else str(target_port)
    )


def _effective_port(scheme: str, port: str) -> str:
    return "" if _DEFAULT_PORTS.get(scheme) == port else port


def _host_matches(hostname: str, host_pattern: str) -> bool:
    host = hostname.lower()
    expected = host_pattern.lower()
    if expected == "*":
        return True
    if expected.startswith("*."):
        domain = expected[2:]
        return host == domain or host.endswith(f".{domain}")
    return host == expected


@lru_cache(maxsize=256)
def _path_regexp(path_pattern: str) -> re.Pattern[str]:
    escaped = re.escape(path_pattern).replace("\\*", ".*")
    return re.compile(f"^{escaped}$")
