"""Gmail connector — ingests email threads as Thread entities."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import base64
import logging
import re
from datetime import UTC, datetime, timedelta
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
    ResourceType,
)
from agentgraph.graph.upsert import upsert_batch

logger = logging.getLogger(__name__)

_STALE_AFTER = 15 * 60

# Strip Re:/Fwd: prefixes for embedding but keep original as title
_SUBJECT_PREFIX_RE = re.compile(r"^(Re|Fwd|FW|RE|FWD):\s*", re.IGNORECASE)
# Gmail API thread/message IDs are lowercase hex strings (16 chars).
# URL hash fragments (legacy Gmail links) are base64-like and are NOT valid API IDs.
_GMAIL_THREAD_ID_RE = re.compile(r"[0-9a-f]{16,}")

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


class GmailConnector(BaseConnector):
    source = "gmail"
    fetch_policy = FetchPolicy(stale_after_seconds=_STALE_AFTER)
    poll_interval: timedelta | None = timedelta(minutes=5)  # type: ignore[assignment]

    def can_handle(self, url: str) -> bool:
        return "mail.google.com" in url

    async def fetch(self, resource_type: ResourceType, resource_id: str, meta: dict[str, str] | None = None) -> EntityBatch:
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

        if resource_id and _GMAIL_THREAD_ID_RE.fullmatch(resource_id):
            # Caller supplied a Gmail API thread ID (hex) — fetch directly.
            logger.info("gmail: fetching specific thread by thread ID %s", resource_id)
            batch = await _fetch_thread_by_thread_id(resource_id)
            await upsert_batch(batch)
            return batch

        logger.debug("gmail: no usable thread ID in resource_id=%r meta=%r — skipping", resource_id, meta)
        return EntityBatch()

    async def poll(self, cursor: dict[str, Any]) -> tuple[EntityBatch, dict[str, Any]]:
        import asyncio

        loop = asyncio.get_event_loop()
        service = await loop.run_in_executor(None, _build_service)

        if not cursor:
            # First run: record the current historyId as the starting point.
            # Nothing is fetched now; subsequent polls pick up new threads from here.
            profile: dict[str, Any] = await loop.run_in_executor(
                None,
                lambda: service.users().getProfile(userId="me").execute(),
            )
            logger.info("gmail poll: initialised cursor at historyId %s", profile["historyId"])
            return EntityBatch(), {"history_id": profile["historyId"]}

        # Incremental poll via history list.
        start_history_id: str = cursor["history_id"]
        thread_ids: set[str] = set()
        page_token: str | None = None
        latest_history_id = start_history_id

        while True:
            kwargs: dict[str, Any] = {
                "userId": "me",
                "startHistoryId": start_history_id,
                "historyTypes": ["messageAdded"],
                "labelId": "INBOX",
            }
            if page_token:
                kwargs["pageToken"] = page_token

            try:
                response: dict[str, Any] = await loop.run_in_executor(
                    None,
                    lambda kw=kwargs: service.users().history().list(**kw).execute(),
                )
            except Exception as exc:
                from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

                if isinstance(exc, HttpError) and exc.resp.status == 404:
                    # historyId expired — reset cursor for full re-sync next run.
                    logger.warning("gmail historyId %s expired, resetting cursor", start_history_id)
                    return EntityBatch(), {}
                raise

            latest_history_id = response.get("historyId", latest_history_id)
            for record in response.get("history", []):
                for msg_added in record.get("messagesAdded", []):
                    thread_ids.add(msg_added["message"]["threadId"])

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        logger.info("gmail poll: fetching %d thread(s)", len(thread_ids))
        combined = EntityBatch()
        for tid in thread_ids:
            try:
                batch = await _fetch_thread_by_thread_id(tid)
                combined.entities.extend(batch.entities)
                combined.persons.extend(batch.persons)
                combined.edges.extend(batch.edges)
            except Exception:
                logger.exception("gmail poll: failed to fetch thread %s", tid)

        return combined, {"history_id": latest_history_id}


async def _fetch_thread_by_thread_id(thread_id: str) -> EntityBatch:
    """Fetch a thread directly by its Gmail thread ID."""
    import asyncio

    loop = asyncio.get_event_loop()
    service = await loop.run_in_executor(None, _build_service)

    thread: dict[str, Any] = await loop.run_in_executor(
        None,
        lambda: service.users().threads().get(
            userId="me", id=thread_id, format="full"
        ).execute(),
    )
    entity, persons, edges = _thread_to_items(thread)
    if not entity:
        return EntityBatch()
    batch = EntityBatch(entities=[entity], persons=persons, edges=edges)
    batch.add_stubs_from(entity)
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
    return await _fetch_thread_by_thread_id(thread_id)


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


async def _list_all_threads(service: Any, loop: Any) -> EntityBatch:
    """Page through all inbox threads and return a combined EntityBatch."""
    combined = EntityBatch()
    page_token: str | None = None

    while True:
        kwargs: dict[str, Any] = {"userId": "me", "maxResults": 500}
        if page_token:
            kwargs["pageToken"] = page_token

        response: dict[str, Any] = await loop.run_in_executor(
            None,
            lambda kw=kwargs: service.users().threads().list(**kw).execute(),
        )

        for thread_stub in response.get("threads", []):
            try:
                batch = await _fetch_thread_by_thread_id(thread_stub["id"])
                combined.entities.extend(batch.entities)
                combined.persons.extend(batch.persons)
                combined.edges.extend(batch.edges)
            except Exception:
                logger.exception("gmail _list_all_threads: failed to fetch thread %s", thread_stub["id"])

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return combined


async def _filter_known_threads(thread_ids: set[str]) -> set[str]:
    """Return only the thread IDs that already exist in the entities table."""
    from agentgraph.db.connection import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT platform_entity_id FROM entities
            WHERE platform = 'gmail' AND platform_entity_id = ANY($1)
            """,
            list(thread_ids),
        )
    return {row["platform_entity_id"] for row in rows}
