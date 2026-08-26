"""RSS feed configuration flow."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import asyncio
import json
import re
import tomllib
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urljoin, urlparse
from xml.etree import ElementTree

import yaml
from agentgraph_connector_web import fetch_http_resource
from agentgraph_connector_web.http import HttpFetchResult
from pydantic import BaseModel, Field


class RssConfig(BaseModel):
    feed_urls: list[str] = Field(default_factory=list)


class OpmlFeed(BaseModel):
    title: str
    feed_url: str
    html_url: str | None = None


_RSS_CONFIG_BEGIN = "# BEGIN AgentGraph managed RSS config"
_RSS_CONFIG_END = "# END AgentGraph managed RSS config"


def load_rss_settings(account_id: str | None = None) -> RssConfig:
    _ = account_id
    data = load_rss_config()
    if data is None:
        raise RuntimeError("RSS feeds not configured. Run: agentgraph connector rss add <feed-url>")
    return RssConfig(**data)


def load_rss_config() -> dict[str, Any] | None:
    """Return RSS feed config."""
    return _load_rss_config()


def save_rss_config(data: Any) -> None:
    payload = data.model_dump(mode="json") if hasattr(data, "model_dump") else dict(data)
    _write_rss_config(_normalise_rss_config(payload))


def _load_rss_config() -> dict[str, Any] | None:
    from agentgraph.config import get_config_paths

    _, CONFIG_FILE, CONFIG_YAML_FILE, _, _ = get_config_paths()

    yaml_config = _load_rss_yaml_config(CONFIG_YAML_FILE)
    if yaml_config is not None:
        return yaml_config
    toml_config = _load_rss_toml_config(CONFIG_FILE)
    if toml_config is not None:
        return toml_config
    return None


def _load_rss_toml_config(config_file: Path) -> dict[str, Any] | None:
    if not config_file.exists():
        return None
    content = config_file.read_text(encoding="utf-8")
    try:
        raw = tomllib.loads(content)
    except Exception:
        return _recover_rss_toml_config(content)
    return _extract_rss_config(raw)


def _recover_rss_toml_config(content: str) -> dict[str, Any] | None:
    """Recover feed URLs from duplicate RSS tables written by older CLI versions."""
    headers = list(re.finditer(r"(?m)^\[connectors\.rss\]\s*$", content))
    feed_urls: list[str] = []
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(content)
        next_table = re.search(r"(?m)^\[", content[header.end() : end])
        if next_table is not None:
            end = header.end() + next_table.start()
        try:
            raw = tomllib.loads(content[header.start() : end])
        except Exception:
            continue
        recovered = _extract_rss_config(raw)
        if recovered is not None:
            feed_urls.extend(cast(list[str], recovered["feed_urls"]))
    if not feed_urls:
        return None
    return _normalise_rss_config({"feed_urls": list(dict.fromkeys(feed_urls))})


def _load_rss_yaml_config(config_file: Path) -> dict[str, Any] | None:
    if not config_file.exists():
        return None
    try:
        raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return _extract_rss_config(raw)


def _extract_rss_config(raw: dict[Any, Any]) -> dict[str, Any] | None:
    connectors = raw.get("connectors")
    if not isinstance(connectors, dict):
        return None
    rss = connectors.get("rss")
    if not isinstance(rss, dict):
        return None
    feed_urls = rss.get("feed_urls")
    if isinstance(feed_urls, list):
        return _normalise_rss_config({"feed_urls": feed_urls})
    return None


def _write_rss_config(config: dict[str, Any]) -> None:
    from agentgraph.config import get_config_paths

    CONFIG_DIR, CONFIG_FILE, CONFIG_YAML_FILE, _, _ = get_config_paths()

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_YAML_FILE.exists():
        _write_rss_yaml_config(CONFIG_YAML_FILE, config)
        return
    existing = CONFIG_FILE.read_text(encoding="utf-8") if CONFIG_FILE.exists() else ""
    prefix = _strip_unmanaged_rss_config(_strip_managed_rss_config(existing)).strip()
    block = _format_rss_config_block(config)
    content = f"{prefix}\n\n{block}" if prefix else block
    CONFIG_FILE.write_text(content, encoding="utf-8")


def _rss_config_write_path() -> Path:
    from agentgraph.config import get_config_paths

    _, CONFIG_FILE, CONFIG_YAML_FILE, _, _ = get_config_paths()

    return CONFIG_YAML_FILE if CONFIG_YAML_FILE.exists() else CONFIG_FILE


def _write_rss_yaml_config(
    config_file: Path,
    config: dict[str, Any],
) -> None:
    raw: dict[str, Any]
    if config_file.exists():
        loaded = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        raw = loaded if isinstance(loaded, dict) else {}
    else:
        raw = {}
    connectors = raw.get("connectors")
    if not isinstance(connectors, dict):
        connectors = {}
    connectors["rss"] = _normalise_rss_config(config)
    raw["connectors"] = connectors
    config_file.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def _normalise_rss_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "feed_urls": [
            str(feed_url)
            for feed_url in config.get("feed_urls", [])
            if isinstance(feed_url, str) and feed_url
        ],
    }


def _strip_managed_rss_config(content: str) -> str:
    begin = content.find(_RSS_CONFIG_BEGIN)
    if begin == -1:
        return content
    end = content.find(_RSS_CONFIG_END, begin)
    if end == -1:
        return content[:begin]
    return f"{content[:begin]}{content[end + len(_RSS_CONFIG_END) :]}"


def _strip_unmanaged_rss_config(content: str) -> str:
    """Remove a legacy RSS TOML table before replacing it with the managed block."""
    return re.sub(
        r"(?ms)^\[connectors\.rss\]\s*\n.*?(?=^# BEGIN AgentGraph managed |^\[(?!\[?connectors\.rss(?:\.|\]))|\Z)",
        "",
        content,
    )


def _format_rss_config_block(config: dict[str, Any]) -> str:
    lines = [
        _RSS_CONFIG_BEGIN,
        "[connectors.rss]",
    ]
    feed_urls = [
        str(feed_url)
        for feed_url in config.get("feed_urls", [])
        if isinstance(feed_url, str) and feed_url
    ]
    lines.append("feed_urls = [")
    lines.extend(f"  {_toml_string(url)}," for url in feed_urls)
    lines.append("]")
    lines.append(_RSS_CONFIG_END)
    return "\n".join(lines) + "\n"


def _toml_string(value: str) -> str:
    return json.dumps(value)


def add_feed_urls(
    feed_urls: list[str],
    *,
    validate: bool = True,
) -> RssConfig:
    """Add feed URLs to the configured RSS feed list and return the updated config."""
    selected_feed_urls = [part.strip() for part in feed_urls if part.strip()]
    if not selected_feed_urls:
        raise ValueError("Usage: agentgraph connector rss add <feed-url> [feed-url...]")
    if validate:
        selected_feed_urls = resolve_feed_sources(selected_feed_urls)

    try:
        existing = load_rss_settings()
        merged = [*existing.feed_urls]
    except RuntimeError:
        merged = []

    for feed_url in selected_feed_urls:
        if feed_url not in merged:
            merged.append(feed_url)

    config = RssConfig(feed_urls=merged)
    save_rss_config(config)
    return config


def remove_feed_urls(
    feed_urls: list[str],
) -> tuple[RssConfig, list[str]]:
    """Remove configured feeds supplied directly or through a feed discovery page."""
    selected_feed_urls = [part.strip() for part in feed_urls if part.strip()]
    if not selected_feed_urls:
        raise ValueError("Usage: agentgraph connector rss remove <feed-url> [feed-url...]")

    existing = load_rss_settings()
    remove_set = set(_resolve_configured_feed_sources(selected_feed_urls, existing.feed_urls))
    updated_feed_urls = [feed_url for feed_url in existing.feed_urls if feed_url not in remove_set]
    removed_feed_urls = [feed_url for feed_url in existing.feed_urls if feed_url in remove_set]
    if not removed_feed_urls:
        raise ValueError("No matching RSS feed URLs are configured for removal")

    config = RssConfig(feed_urls=updated_feed_urls)
    save_rss_config(config)
    return config, removed_feed_urls


def resolve_feed_sources(sources: list[str]) -> list[str]:
    """Validate user-provided RSS/Atom feed URLs and deduplicate them."""
    resolved: list[str] = []
    seen: set[str] = set()
    for source in sources:
        feed_url = resolve_feed_source(source)
        if feed_url not in seen:
            seen.add(feed_url)
            resolved.append(feed_url)
    return resolved


def resolve_feed_source(source: str) -> str:
    """Return a direct feed URL or the first RSS/Atom alternate link it advertises."""
    candidate = source.strip()
    if not candidate:
        raise ValueError("RSS feed URL cannot be empty")

    parsed, content, base_url = _parse_feed_source(candidate)
    if _is_valid_feed(parsed):
        return candidate
    alternate_feed_url = _find_alternate_feed_url(content, base_url)
    if alternate_feed_url is not None and _is_valid_feed(_parse_feed(alternate_feed_url)):
        return alternate_feed_url
    raise ValueError(f"Not a valid RSS/Atom feed: {candidate}")


def _resolve_configured_feed_sources(sources: list[str], configured_feed_urls: list[str]) -> list[str]:
    """Resolve page sources only when an input is not already a configured feed URL."""
    configured = set(configured_feed_urls)
    return [source if source in configured else resolve_feed_source(source) for source in sources]


def _parse_feed_source(feed_url: str) -> tuple[Any, bytes | None, str]:
    import feedparser  # type: ignore[import-untyped]

    if urlparse(feed_url).scheme not in {"http", "https"}:
        return feedparser.parse(feed_url), _read_local_source_content(feed_url), feed_url
    response = asyncio.run(_fetch_feed_response(feed_url))
    return feedparser.parse(response.content), response.content, response.url


def _parse_feed(feed_url: str) -> Any:
    import feedparser  # type: ignore[import-untyped]

    if urlparse(feed_url).scheme not in {"http", "https"}:
        return feedparser.parse(feed_url)
    return feedparser.parse(asyncio.run(_fetch_feed_content(feed_url)))


def _read_local_source_content(source: str) -> bytes | None:
    parsed = urlparse(source)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
    elif not parsed.scheme:
        path = Path(source)
    else:
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


async def _fetch_feed_response(feed_url: str) -> HttpFetchResult:
    return await fetch_http_resource(
        feed_url,
        headers={
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"
        },
        max_bytes=5_000_000,
        too_large_message="RSS feed response too large: limit is 5000000 bytes",
    )


async def _fetch_feed_content(feed_url: str) -> bytes:
    return (await _fetch_feed_response(feed_url)).content


async def _parse_remote_feed(feed_url: str) -> Any:
    import feedparser  # type: ignore[import-untyped]

    content = await _fetch_feed_content(feed_url)
    return await asyncio.to_thread(feedparser.parse, content)


def _is_valid_feed(parsed: Any) -> bool:
    version = str(getattr(parsed, "version", "") or "")
    if not version:
        return False
    feed = cast(dict[str, Any], getattr(parsed, "feed", {}) or {})
    entries = cast(list[Any], getattr(parsed, "entries", []) or [])
    return bool(feed or entries)


class _AlternateFeedLinkParser(HTMLParser):
    """Find the first RSS or Atom alternate link in an HTML document."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base_url = base_url
        self.feed_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link" or self.feed_url is not None:
            return
        attributes = dict(attrs)
        rel = attributes.get("rel")
        feed_type = attributes.get("type")
        href = attributes.get("href")
        if rel is None or feed_type is None or href is None:
            return
        if "alternate" not in rel.lower().split():
            return
        media_type = feed_type.split(";", maxsplit=1)[0].strip().lower()
        if media_type not in {"application/rss+xml", "application/atom+xml"}:
            return
        feed_url = urljoin(self._base_url, href)
        if urlparse(feed_url).scheme in {"", "file", "http", "https"}:
            self.feed_url = feed_url


def _find_alternate_feed_url(content: bytes | None, base_url: str) -> str | None:
    if content is None:
        return None
    parser = _AlternateFeedLinkParser(base_url)
    try:
        parser.feed(content.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    return parser.feed_url


def parse_opml_feeds(path: str | Path) -> list[OpmlFeed]:
    """Parse feed outlines from an OPML file."""
    source_path = _opml_source_path(path)
    if not source_path.exists():
        raise FileNotFoundError(f"OPML file not found: {source_path}")

    try:
        root = ElementTree.parse(source_path).getroot()
    except ElementTree.ParseError as exc:
        raise ValueError(f"Could not parse OPML file: {exc}") from exc

    feeds: list[OpmlFeed] = []
    seen: set[str] = set()
    for outline in root.iter("outline"):
        feed_url = (outline.attrib.get("xmlUrl") or outline.attrib.get("xmlurl") or "").strip()
        if not feed_url or feed_url in seen:
            continue
        seen.add(feed_url)
        title = (
            outline.attrib.get("title")
            or outline.attrib.get("text")
            or outline.attrib.get("description")
            or feed_url
        )
        html_url = (outline.attrib.get("htmlUrl") or outline.attrib.get("htmlurl") or "").strip()
        feeds.append(OpmlFeed(title=title.strip(), feed_url=feed_url, html_url=html_url or None))
    return feeds


def _opml_source_path(path: str | Path) -> Path:
    return _local_file_path(path, kind="OPML")


def _local_file_path(path: str | Path, *, kind: str) -> Path:
    raw_path = str(path)
    parsed = urlparse(raw_path)
    if parsed.scheme == "file":
        if parsed.netloc not in ("", "localhost"):
            raise ValueError(f"Unsupported {kind} file URI host: {parsed.netloc}")
        return Path(unquote(parsed.path)).expanduser()
    return Path(path).expanduser()


def select_opml_feeds(
    feeds: list[OpmlFeed],
    *,
    include_all: bool = False,
    selection: str | None = None,
    configured_feed_urls: list[str] | None = None,
) -> list[OpmlFeed]:
    if include_all:
        return feeds
    if selection is not None:
        selected_indexes = _parse_feed_selection(selection, len(feeds))
        return [feeds[index - 1] for index in selected_indexes]
    return _prompt_for_opml_feeds(feeds, configured_feed_urls=configured_feed_urls or [])


def import_opml_feeds(
    path: str | Path,
    *,
    include_all: bool = False,
    selection: str | None = None,
) -> tuple[RssConfig, list[OpmlFeed], list[OpmlFeed]]:
    feeds = parse_opml_feeds(path)
    if not feeds:
        raise ValueError("No RSS/Atom feeds found in OPML file")

    configured_feed_urls: list[str] = []
    try:
        configured_feed_urls = load_rss_settings().feed_urls
    except RuntimeError:
        configured_feed_urls = []

    selected_feeds = select_opml_feeds(
        feeds,
        include_all=include_all,
        selection=selection,
        configured_feed_urls=configured_feed_urls,
    )
    if not selected_feeds:
        raise ValueError("No feeds selected")

    config = add_feed_urls([feed.feed_url for feed in selected_feeds])
    return config, feeds, selected_feeds


def _parse_feed_selection(selection: str, feed_count: int) -> list[int]:
    indexes: list[int] = []
    seen: set[int] = set()
    for raw_part in selection.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            start_raw, end_raw = part.split("-", 1)
            try:
                start = int(start_raw.strip())
                end = int(end_raw.strip())
            except ValueError as exc:
                raise ValueError(f"Invalid feed selection: {selection}") from exc
            if start > end:
                raise ValueError(f"Invalid feed selection range: {part}")
            candidates = range(start, end + 1)
        else:
            try:
                candidates = range(int(part), int(part) + 1)
            except ValueError as exc:
                raise ValueError(f"Invalid feed selection: {selection}") from exc
        for index in candidates:
            if index < 1 or index > feed_count:
                raise ValueError(f"Feed selection {index} is out of range 1-{feed_count}")
            if index not in seen:
                seen.add(index)
                indexes.append(index)
    return indexes


def _prompt_for_opml_feeds(
    feeds: list[OpmlFeed],
    *,
    configured_feed_urls: list[str],
) -> list[OpmlFeed]:
    import sys

    if not sys.stdin.isatty():
        raise ValueError("Use --all or --select <indexes> when importing OPML non-interactively")

    try:
        return _checkbox_select_opml_feeds(feeds, configured_feed_urls=configured_feed_urls)
    except ImportError:
        return _prompt_for_opml_feeds_numeric(feeds)


def _checkbox_select_opml_feeds(
    feeds: list[OpmlFeed],
    *,
    configured_feed_urls: list[str],
) -> list[OpmlFeed]:
    import questionary  # type: ignore[import-untyped]

    configured = set(configured_feed_urls)
    choices = [
        questionary.Choice(
            title=f"{feed.title} ({feed.feed_url})",
            value=feed.feed_url,
            checked=feed.feed_url in configured,
        )
        for feed in feeds
    ]
    selected_urls = questionary.checkbox(
        f"Select feeds to add ({len(feeds)} found):",
        choices=choices,
    ).ask()
    if selected_urls is None:
        raise ValueError("No feeds selected")
    selected = set(cast(list[str], selected_urls))
    return [feed for feed in feeds if feed.feed_url in selected]


def _prompt_for_opml_feeds_numeric(feeds: list[OpmlFeed]) -> list[OpmlFeed]:
    import typer

    typer.echo(f"Found {len(feeds)} feed(s) in OPML:")
    for index, feed in enumerate(feeds, start=1):
        typer.echo(f"  {index}. {feed.title} - {feed.feed_url}")
    if typer.confirm("Add all feeds?", default=True):
        return feeds
    selection = typer.prompt("Feed numbers to add (comma-separated, ranges allowed)").strip()
    return select_opml_feeds(feeds, selection=selection)


async def preview_feed(feed_url: str, *, count: int = 3) -> dict[str, Any]:
    """Fetch and parse a small preview from an RSS/Atom feed URL."""
    import feedparser  # type: ignore[import-untyped]

    if urlparse(feed_url).scheme in {"http", "https"}:
        parsed: Any = await _parse_remote_feed(feed_url)
    else:
        parsed = await asyncio.to_thread(feedparser.parse, feed_url)
    entries = [
        {
            "title": str(
                entry.get("title") or entry.get("id") or entry.get("link") or "(untitled)"
            ),
            "link": str(entry.get("link") or ""),
        }
        for entry in cast(list[Any], parsed.entries)[: max(1, min(count, 50))]
    ]
    feed = cast(dict[str, Any], parsed.feed)
    return {
        "title": str(feed.get("title") or feed_url),
        "feed_url": feed_url,
        "entries": entries,
        "bozo": bool(parsed.bozo),
        "bozo_exception": str(parsed.bozo_exception) if parsed.bozo else None,
    }


async def verify_rss_auth(account_id: str | None = None) -> tuple[str, str | None]:
    try:
        settings = load_rss_settings(account_id)
    except RuntimeError:
        return ("missing", None)

    if not settings.feed_urls:
        return ("invalid", "No RSS feed URLs configured")

    try:
        preview = await preview_feed(settings.feed_urls[0], count=1)
    except Exception as exc:
        return ("invalid", str(exc))

    entry_count = len(cast(list[object], preview.get("entries") or []))
    if preview.get("bozo") and entry_count == 0:
        return ("invalid", str(preview.get("bozo_exception") or "Feed could not be parsed"))
    return ("ok", f"{len(settings.feed_urls)} feed(s), sample returned {entry_count} article(s)")


def run_rss_flow(
    account_id: str | None = None,
    add: bool = False,
) -> None:
    _ = (account_id, add)
    import asyncio

    import typer

    typer.echo(
        "\n"
        "RSS setup does not need authentication. Provide one or more RSS/Atom feed URLs,\n"
        "and AgentGraph will fetch those feeds directly.\n"
    )
    raw_feeds: str = typer.prompt("RSS/Atom feed URLs (comma-separated)").strip()
    selected_feed_urls = resolve_feed_sources(
        [part.strip() for part in raw_feeds.split(",") if part.strip()]
    )

    config = RssConfig(feed_urls=selected_feed_urls)
    save_rss_config(config)

    typer.echo(f"\nRSS feeds saved to {_rss_config_write_path()}")
    if selected_feed_urls:
        typer.echo("Checking configured feed(s)...")

        async def _check() -> None:
            status, detail = await verify_rss_auth()
            if status == "ok":
                typer.echo(f"RSS feed check passed: {detail}")
                preview = await preview_feed(selected_feed_urls[0], count=3)
                entries = cast(list[dict[str, str]], preview.get("entries") or [])
                if entries:
                    typer.echo("Sample articles from first feed:")
                    for item in entries[:3]:
                        typer.echo(f"  - {item['title']}")
            else:
                typer.echo(f"RSS feed check failed: {detail or status}")

        asyncio.run(_check())
