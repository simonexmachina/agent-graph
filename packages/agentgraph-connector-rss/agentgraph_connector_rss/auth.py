"""RSS feed configuration flow."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urljoin, urlparse
from xml.etree import ElementTree

import yaml
from pydantic import BaseModel, Field

from agentgraph_connector_rss.tls import feed_tls_verify


class RssConfig(BaseModel):
    feed_urls: list[str] = Field(default_factory=list)


class OpmlFeed(BaseModel):
    title: str
    feed_url: str
    html_url: str | None = None


@dataclass(frozen=True)
class HtmlSource:
    text: str
    base_url: str


_RSS_CONFIG_BEGIN = "# BEGIN AgentGraph managed RSS config"
_RSS_CONFIG_END = "# END AgentGraph managed RSS config"


class _FeedLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link":
            return
        attr_map = {name.lower(): value for name, value in attrs if value is not None}
        rel_tokens = {token.lower() for token in attr_map.get("rel", "").split()}
        if "alternate" not in rel_tokens:
            return
        link_type = attr_map.get("type", "").lower()
        if link_type not in {"application/rss+xml", "application/atom+xml", "text/xml"}:
            return
        href = attr_map.get("href", "").strip()
        if href:
            self.hrefs.append(href)


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
    from agentgraph.config import CONFIG_FILE, CONFIG_YAML_FILE

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
    try:
        raw = tomllib.loads(config_file.read_text(encoding="utf-8"))
    except Exception:
        return None
    return _extract_rss_config(raw)


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
    from agentgraph.config import CONFIG_DIR, CONFIG_FILE, CONFIG_YAML_FILE

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_YAML_FILE.exists():
        _write_rss_yaml_config(CONFIG_YAML_FILE, config)
        return
    existing = CONFIG_FILE.read_text(encoding="utf-8") if CONFIG_FILE.exists() else ""
    prefix = _strip_managed_rss_config(existing).rstrip()
    block = _format_rss_config_block(config)
    content = f"{prefix}\n\n{block}" if prefix else block
    CONFIG_FILE.write_text(content, encoding="utf-8")


def _rss_config_write_path() -> Path:
    from agentgraph.config import CONFIG_FILE, CONFIG_YAML_FILE

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
    lines.append(f"feed_urls = [{', '.join(_toml_string(url) for url in feed_urls)}]")
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
    """Remove exact feed URLs from the configured RSS feed list."""
    selected_feed_urls = [part.strip() for part in feed_urls if part.strip()]
    if not selected_feed_urls:
        raise ValueError("Usage: agentgraph connector rss remove <feed-url> [feed-url...]")

    existing = load_rss_settings()
    remove_set = set(selected_feed_urls)
    updated_feed_urls = [feed_url for feed_url in existing.feed_urls if feed_url not in remove_set]
    removed_feed_urls = [feed_url for feed_url in existing.feed_urls if feed_url in remove_set]
    if not removed_feed_urls:
        raise ValueError("No matching RSS feed URLs are configured for removal")

    config = RssConfig(feed_urls=updated_feed_urls)
    save_rss_config(config)
    return config, removed_feed_urls


def resolve_feed_sources(sources: list[str]) -> list[str]:
    """Resolve user-provided feed or HTML sources to validated RSS/Atom feed URLs."""
    resolved: list[str] = []
    seen: set[str] = set()
    for source in sources:
        feed_url = resolve_feed_source(source)
        if feed_url not in seen:
            seen.add(feed_url)
            resolved.append(feed_url)
    return resolved


def resolve_feed_source(source: str) -> str:
    """Return a valid feed URL, discovering it from HTML when necessary."""
    candidate = source.strip()
    if not candidate:
        raise ValueError("RSS feed URL cannot be empty")

    parsed = _parse_feed(candidate)
    if _is_valid_feed(parsed):
        return candidate

    html_source = _load_html_source(candidate)
    if html_source is None:
        raise ValueError(f"Not a valid RSS/Atom feed: {candidate}")

    feed_links = _extract_feed_links(html_source.text, html_source.base_url)
    if not feed_links:
        raise ValueError(f"No RSS/Atom feed link found in HTML: {candidate}")

    for feed_link in feed_links:
        if _is_valid_feed(_parse_feed(feed_link)):
            return feed_link
    raise ValueError(f"No valid RSS/Atom feed found in HTML: {candidate}")


def _parse_feed(feed_url: str) -> Any:
    import feedparser  # type: ignore[import-untyped]
    import httpx

    if urlparse(feed_url).scheme in {"http", "https"}:
        response = httpx.get(
            feed_url,
            follow_redirects=True,
            timeout=10,
            verify=feed_tls_verify(feed_url),
        )
        response.raise_for_status()
        return feedparser.parse(response.content)
    return feedparser.parse(feed_url)


def _is_valid_feed(parsed: Any) -> bool:
    version = str(getattr(parsed, "version", "") or "")
    if not version:
        return False
    feed = cast(dict[str, Any], getattr(parsed, "feed", {}) or {})
    entries = cast(list[Any], getattr(parsed, "entries", []) or [])
    return bool(feed or entries)


def _load_html_source(source: str) -> HtmlSource | None:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        return _fetch_html_url(source)
    if parsed.scheme == "file":
        path = _local_file_path(source, kind="HTML")
        return _read_html_file(path)
    if parsed.scheme:
        return None
    path = Path(source).expanduser()
    if path.exists():
        return _read_html_file(path)
    return None


def _fetch_html_url(url: str) -> HtmlSource | None:
    import httpx

    try:
        response = httpx.get(
            url,
            follow_redirects=True,
            timeout=10,
            verify=feed_tls_verify(url),
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    text = response.text
    content_type = response.headers.get("content-type", "").lower()
    if "html" not in content_type and not _looks_like_html(text):
        return None
    return HtmlSource(text=text, base_url=str(response.url))


def _read_html_file(path: Path) -> HtmlSource | None:
    text = path.read_text(encoding="utf-8")
    if not _looks_like_html(text):
        return None
    return HtmlSource(text=text, base_url=path.resolve().as_uri())


def _looks_like_html(text: str) -> bool:
    sample = text[:500].lower()
    return "<html" in sample or "<!doctype html" in sample or "<link" in sample


def _extract_feed_links(html: str, base_url: str) -> list[str]:
    parser = _FeedLinkParser()
    parser.feed(html)
    return [urljoin(base_url, href) for href in parser.hrefs]


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
    import asyncio

    import feedparser  # type: ignore[import-untyped]

    parsed: Any = await asyncio.to_thread(feedparser.parse, feed_url)
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
