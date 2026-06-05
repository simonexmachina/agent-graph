"""RSS feed configuration flow."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree

from pydantic import BaseModel, Field


class RssCredentials(BaseModel):
    feed_urls: list[str] = Field(default_factory=list)
    account_id: str | None = None
    label: str | None = None


class OpmlFeed(BaseModel):
    title: str
    feed_url: str
    html_url: str | None = None


def load_rss_creds(account_id: str | None = None) -> RssCredentials:
    from agentgraph.auth.credentials import load_platform_account

    data = load_platform_account("rss", account_id)
    if data is None:
        raise RuntimeError("RSS feeds not configured. Run: agentgraph auth rss")
    return RssCredentials(**data)


def list_rss_accounts() -> list[dict[str, str | None]]:
    from agentgraph.auth.credentials import load_platform_accounts

    results: list[dict[str, str | None]] = []
    for raw in load_platform_accounts("rss"):
        try:
            creds = RssCredentials(**raw)
        except Exception:
            continue
        account_id = str(raw.get("account_id") or creds.account_id or "rss")
        label = creds.label or f"{len(creds.feed_urls)} RSS feed(s)"
        results.append({
            "account_id": account_id,
            "label": label,
            "feed_count": str(len(creds.feed_urls)),
        })
    return results


def add_feed_urls(
    feed_urls: list[str],
    *,
    account_id: str | None = None,
) -> RssCredentials:
    """Add feed URLs to the configured RSS account and return the updated credentials."""
    from agentgraph.auth.credentials import save_platform, upsert_platform_account

    selected_feed_urls = [part.strip() for part in feed_urls if part.strip()]
    if not selected_feed_urls:
        raise ValueError("Usage: agentgraph connector rss add <feed-url> [feed-url...]")

    resolved_account_id = account_id or "rss"
    existing_accounts = list_rss_accounts()
    try:
        existing = load_rss_creds(resolved_account_id)
        label = existing.label or "RSS"
        merged = [*existing.feed_urls]
    except RuntimeError:
        label = "RSS"
        merged = []

    for feed_url in selected_feed_urls:
        if feed_url not in merged:
            merged.append(feed_url)

    creds = RssCredentials(
        feed_urls=merged,
        account_id=resolved_account_id,
        label=label,
    )
    if existing_accounts:
        upsert_platform_account("rss", resolved_account_id, creds, make_default=True)
    else:
        save_platform("rss", {**creds.model_dump(mode="json"), "account_id": resolved_account_id})
    return creds


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
    raw_path = str(path)
    parsed = urlparse(raw_path)
    if parsed.scheme == "file":
        if parsed.netloc not in ("", "localhost"):
            raise ValueError(f"Unsupported OPML file URI host: {parsed.netloc}")
        return Path(unquote(parsed.path)).expanduser()
    return Path(path).expanduser()


def select_opml_feeds(
    feeds: list[OpmlFeed],
    *,
    include_all: bool = False,
    selection: str | None = None,
) -> list[OpmlFeed]:
    if include_all:
        return feeds
    if selection is not None:
        selected_indexes = _parse_feed_selection(selection, len(feeds))
        return [feeds[index - 1] for index in selected_indexes]
    return _prompt_for_opml_feeds(feeds)


def import_opml_feeds(
    path: str | Path,
    *,
    account_id: str | None = None,
    include_all: bool = False,
    selection: str | None = None,
) -> tuple[RssCredentials, list[OpmlFeed], list[OpmlFeed]]:
    feeds = parse_opml_feeds(path)
    if not feeds:
        raise ValueError("No RSS/Atom feeds found in OPML file")

    selected_feeds = select_opml_feeds(feeds, include_all=include_all, selection=selection)
    if not selected_feeds:
        raise ValueError("No feeds selected")

    creds = add_feed_urls([feed.feed_url for feed in selected_feeds], account_id=account_id)
    return creds, feeds, selected_feeds


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


def _prompt_for_opml_feeds(feeds: list[OpmlFeed]) -> list[OpmlFeed]:
    import sys

    import typer

    if not sys.stdin.isatty():
        raise ValueError("Use --all or --select <indexes> when importing OPML non-interactively")

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
            "title": str(entry.get("title") or entry.get("id") or entry.get("link") or "(untitled)"),
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
        creds = load_rss_creds(account_id)
    except RuntimeError:
        return ("missing", None)

    if not creds.feed_urls:
        return ("invalid", "No RSS feed URLs configured")

    try:
        preview = await preview_feed(creds.feed_urls[0], count=1)
    except Exception as exc:
        return ("invalid", str(exc))

    entry_count = len(cast(list[object], preview.get("entries") or []))
    if preview.get("bozo") and entry_count == 0:
        return ("invalid", str(preview.get("bozo_exception") or "Feed could not be parsed"))
    return ("ok", f"{len(creds.feed_urls)} feed(s), sample returned {entry_count} article(s)")


def run_rss_flow(
    account_id: str | None = None,
    add: bool = False,
) -> None:
    import asyncio

    import typer

    from agentgraph.auth.credentials import save_platform, upsert_platform_account
    from agentgraph.config import CREDENTIALS_FILE

    typer.echo(
        "\n"
        "RSS authentication does not need an API key. Provide one or more RSS/Atom feed URLs,\n"
        "and AgentGraph will fetch those feeds directly.\n"
    )
    raw_feeds: str = typer.prompt("RSS/Atom feed URLs (comma-separated)").strip()
    selected_feed_urls = [part.strip() for part in raw_feeds.split(",") if part.strip()]
    label: str = typer.prompt("Account label", default="RSS").strip()
    resolved_account_id = account_id or "rss"

    creds = RssCredentials(
        feed_urls=selected_feed_urls,
        account_id=resolved_account_id,
        label=label,
    )
    if not add and account_id is None and not list_rss_accounts():
        save_platform("rss", {**creds.model_dump(mode="json"), "account_id": resolved_account_id})
    else:
        upsert_platform_account("rss", resolved_account_id, creds, make_default=True)

    typer.echo(f"\nRSS feeds saved to {CREDENTIALS_FILE}")
    if selected_feed_urls:
        typer.echo("Checking configured feed(s)...")

        async def _check() -> None:
            status, detail = await verify_rss_auth(resolved_account_id)
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
