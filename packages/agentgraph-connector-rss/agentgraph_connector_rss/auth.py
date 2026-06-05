"""RSS feed configuration flow."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, Field


class RssCredentials(BaseModel):
    feed_urls: list[str] = Field(default_factory=list)
    account_id: str | None = None
    label: str | None = None


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
    feed_urls = [part.strip() for part in raw_feeds.split(",") if part.strip()]
    label: str = typer.prompt("Account label", default="RSS").strip()
    resolved_account_id = account_id or "rss"

    creds = RssCredentials(
        feed_urls=feed_urls,
        account_id=resolved_account_id,
        label=label,
    )
    if not add and account_id is None and not list_rss_accounts():
        save_platform("rss", {**creds.model_dump(mode="json"), "account_id": resolved_account_id})
    else:
        upsert_platform_account("rss", resolved_account_id, creds, make_default=True)

    typer.echo(f"\nRSS feeds saved to {CREDENTIALS_FILE}")
    if feed_urls:
        typer.echo("Checking configured feed(s)...")

        async def _check() -> None:
            status, detail = await verify_rss_auth(resolved_account_id)
            if status == "ok":
                typer.echo(f"RSS feed check passed: {detail}")
                preview = await preview_feed(feed_urls[0], count=3)
                entries = cast(list[dict[str, str]], preview.get("entries") or [])
                if entries:
                    typer.echo("Sample articles from first feed:")
                    for item in entries[:3]:
                        typer.echo(f"  - {item['title']}")
            else:
                typer.echo(f"RSS feed check failed: {detail or status}")

        asyncio.run(_check())
