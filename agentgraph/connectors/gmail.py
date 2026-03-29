"""Gmail connector — ingests email threads as Thread entities."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import base64
import logging
import re
from datetime import UTC, datetime
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

from googleapiclient.discovery import build  # type: ignore[import-untyped]

from agentgraph.auth.google_provider import get_provider
from agentgraph.connectors.base import (
    BaseConnector,
    EdgeRecord,
    EntityBatch,
    EntityRecord,
    FetchPolicy,
    PersonRecord,
)
from agentgraph.graph.upsert import upsert_batch

logger = logging.getLogger(__name__)

_STALE_AFTER = 15 * 60

# Strip Re:/Fwd: prefixes for embedding but keep original as title
_SUBJECT_PREFIX_RE = re.compile(r"^(Re|Fwd|FW|RE|FWD):\s*", re.IGNORECASE)

# Simple HTML tag stripper for fallback body extraction
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_WS_RE = re.compile(r"\n{3,}")


def _build_service() -> Any:
    return build("gmail", "v1", credentials=get_provider().get_credentials())


def _get_header(headers: list[dict[str, str]], name: str) -> str:
    """Return the first header value matching name (case-insensitive)."""
    name_lower = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_lower:
            return h.get("value", "")
    return ""


def _extract_body(payload: dict[str, Any]) -> str:
    """Recursively extract plain-text body from a MIME payload.

    Prefers text/plain; falls back to text/html with tags stripped.
    """
    mime_type: str = payload.get("mimeType", "")

    if mime_type == "text/plain":
        data = (payload.get("body") or {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    if mime_type == "text/html":
        data = (payload.get("body") or {}).get("data", "")
        if data:
            html = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            text = _HTML_TAG_RE.sub(" ", html)
            text = _HTML_WS_RE.sub("\n\n", text)
            return text.strip()

    # Recurse into multipart
    for part in payload.get("parts", []):
        result = _extract_body(part)
        if result:
            return result

    return ""


def _parse_email_addresses(header_value: str) -> list[tuple[str, str]]:
    """Parse a comma-separated address header into (display_name, email) pairs."""
    results: list[tuple[str, str]] = []
    for part in header_value.split(","):
        part = part.strip()
        if not part:
            continue
        name, addr = parseaddr(part)
        addr = addr.lower().strip()
        if addr:
            results.append((name, addr))
    return results


def _format_date(date_str: str) -> str:
    """Return a short date string from an RFC 2822 date header."""
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return date_str


_FETCH_LIMIT = 5   # threads to fetch per observation


class GmailConnector(BaseConnector):
    source = "gmail"
    fetch_policy = FetchPolicy(stale_after_seconds=_STALE_AFTER)

    def can_handle(self, url: str) -> bool:
        return "mail.google.com" in url

    async def last_synced_at(self, resource_id: str) -> datetime | None:  # type: ignore[override]
        from agentgraph.db.connection import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT max(synced_at) FROM entities WHERE platform = 'gmail'"
            )

    async def fetch(self, resource_type: str, resource_id: str, meta: dict[str, str] | None = None) -> EntityBatch:
        if resource_type != "thread":
            logger.debug("gmail connector: unsupported resource_type %r — skipping", resource_type)
            return EntityBatch()

        gmail_message_id = (meta or {}).get("gmail_message_id")
        if gmail_message_id:
            # Content script extracted the hex message ID from the DOM — use it
            # to fetch the exact thread via the API.
            logger.info("gmail: fetching specific thread via message ID %s", gmail_message_id)
            batch = await _fetch_thread_by_message_id(gmail_message_id)
            await upsert_batch(batch)
            return batch

        # No message ID available (content script not yet loaded, or non-thread URL).
        # Fall back to fetching the N most recent threads, gated by stale policy.
        last_sync = await self.last_synced_at(resource_id)
        if self.fetch_policy.decide(last_sync) == FetchPolicy.FRESH:
            logger.debug("gmail: recently synced — skipping")
            return EntityBatch()

        batch = await _fetch_recent_threads(limit=_FETCH_LIMIT)
        await upsert_batch(batch)
        return batch


async def _fetch_thread_by_message_id(message_id: str) -> EntityBatch:
    """Fetch the thread containing a specific message, identified by its hex API message ID."""
    import asyncio

    loop = asyncio.get_event_loop()
    service = await loop.run_in_executor(None, _build_service)

    # Resolve message → thread ID
    msg: dict[str, Any] = await loop.run_in_executor(
        None,
        lambda: service.users().messages().get(
            userId="me", id=message_id, format="minimal"
        ).execute(),
    )
    thread_id: str = msg["threadId"]

    thread: dict[str, Any] = await loop.run_in_executor(
        None,
        lambda: service.users().threads().get(  # noqa: B023
            userId="me", id=thread_id, format="full"
        ).execute(),
    )
    entity, persons, edges = _thread_to_items(thread)
    if not entity:
        return EntityBatch()
    return EntityBatch(entities=[entity], persons=persons, edges=edges)


async def _fetch_recent_threads(limit: int) -> EntityBatch:
    """Fetch the N most recently active inbox threads."""
    import asyncio

    loop = asyncio.get_event_loop()
    service = await loop.run_in_executor(None, _build_service)

    result: dict[str, Any] = await loop.run_in_executor(
        None,
        lambda: service.users().threads().list(
            userId="me", q="in:anywhere", maxResults=limit
        ).execute(),
    )
    thread_stubs: list[dict[str, Any]] = result.get("threads", [])
    if not thread_stubs:
        return EntityBatch()

    all_entities: list[EntityRecord] = []
    all_persons: list[PersonRecord] = []
    all_edges: list[EdgeRecord] = []

    for stub in thread_stubs:
        tid = stub["id"]
        thread: dict[str, Any] = await loop.run_in_executor(
            None,
            lambda: service.users().threads().get(  # noqa: B023
                userId="me", id=tid, format="full"
            ).execute(),
        )
        entity, persons, edges = _thread_to_items(thread)
        if entity:
            all_entities.append(entity)
            all_persons.extend(persons)
            all_edges.extend(edges)

    return EntityBatch(entities=all_entities, persons=all_persons, edges=all_edges)


def _thread_to_items(
    thread: dict[str, Any],
) -> tuple[EntityRecord | None, list[PersonRecord], list[EdgeRecord]]:
    """Convert a Gmail thread (full format) into graph items."""
    messages: list[dict[str, Any]] = thread.get("messages", [])
    if not messages:
        return None, [], []

    thread_id: str = thread["id"]

    first_headers = messages[0].get("payload", {}).get("headers", [])
    subject = _get_header(first_headers, "Subject") or "(no subject)"

    content_blocks: list[str] = []
    persons: list[PersonRecord] = []
    edges: list[EdgeRecord] = []
    seen_emails: set[str] = set()
    first_sender_email: str | None = None

    for msg in messages:
        payload = msg.get("payload", {})
        headers = payload.get("headers", [])

        from_header = _get_header(headers, "From")
        to_header   = _get_header(headers, "To")
        cc_header   = _get_header(headers, "Cc")
        date_header = _get_header(headers, "Date")

        body = _extract_body(payload).strip()

        block_lines = [f"**From:** {from_header}", f"**Date:** {_format_date(date_header)}"]
        if to_header:
            block_lines.append(f"**To:** {to_header}")
        block_lines.extend(["", body or "*(empty)*"])
        content_blocks.append("\n".join(block_lines))

        for display_name, email in _parse_email_addresses(
            f"{from_header},{to_header},{cc_header}"
        ):
            if email in seen_emails:
                continue
            seen_emails.add(email)
            persons.append(PersonRecord(
                platform="gmail",
                platform_user_id=email,
                canonical_email=email,
                display_name=display_name or None,
            ))
            if first_sender_email is None:
                _, sender_addr = parseaddr(from_header)
                if sender_addr.lower() == email:
                    first_sender_email = email

    content = "\n\n---\n\n".join(content_blocks)

    for email in seen_emails:
        edge_type = "authored" if email == first_sender_email else "participated_in"
        edges.append(EdgeRecord(
            edge_type=edge_type,
            source_platform_user_id=email,
            target_platform_entity_id=thread_id,
            platform="gmail",
        ))

    label_ids: list[str] = messages[0].get("labelIds", [])
    entity = EntityRecord(
        entity_type="Thread",
        platform="gmail",
        platform_entity_id=thread_id,
        title=subject,
        content=content,
        updated_at=datetime.now(UTC),
        metadata={
            "message_count": len(messages),
            "snippet": thread.get("snippet", ""),
            "label_ids": ",".join(label_ids),
        },
    )
    return entity, persons, edges
