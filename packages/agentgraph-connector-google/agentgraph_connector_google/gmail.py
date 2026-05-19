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

from agentgraph.auth.google_provider import (
    get_credentials as google_credentials,
    get_user_email,
    list_google_accounts,
    verify_google_auth,
)
from agentgraph.connectors.base import (
    BaseConnector,
    ConnectorAccount,
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


def _build_service(account_id: str | None = None) -> Any:
    return build("gmail", "v1", credentials=google_credentials(account_id))


def _build_service_for(account_id: str | None) -> Any:
    return _build_service(account_id) if account_id is not None else _build_service()


def _get_header(headers: list[dict[str, str]], name: str) -> str:
    """Return the first header value matching name (case-insensitive)."""
    name_lower = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_lower:
            return h.get("value", "")
    return ""


def _extract_body(payload: dict[str, Any]) -> str:
    """Recursively extract body from a MIME payload, preferring HTML (via html2text)."""
    import html2text  # type: ignore[import-untyped]

    def _decode(data: str) -> str:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    def _collect(part: dict[str, Any], html_parts: list[str], text_parts: list[str]) -> None:
        mime_type: str = part.get("mimeType", "")
        data: str = (part.get("body") or {}).get("data", "")
        if mime_type == "text/html" and data:
            html_parts.append(_decode(data))
        elif mime_type == "text/plain" and data:
            text_parts.append(_decode(data))
        for child in part.get("parts", []):
            _collect(child, html_parts, text_parts)

    html_parts: list[str] = []
    text_parts: list[str] = []
    _collect(payload, html_parts, text_parts)

    if html_parts:
        h = html2text.HTML2Text()
        h.ignore_images = True
        h.body_width = 0
        return h.handle("\n".join(html_parts)).strip()
    return "\n".join(text_parts).strip()


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
    sync_horizon_days: int = 90  # How far back to look on the initial bulk ingest
    url_patterns = ["https://mail.google.com/*"]
    auth_description = "Gmail conversations (last 90 days by default): Thread entities containing full message bodies with senders, recipients, and cc participants."
    auth_label = "google"

    @classmethod
    def run_auth_flow(cls, account_id: str | None = None, add: bool = False) -> None:
        from agentgraph_connector_google.auth import run_oauth_flow
        run_oauth_flow(account_id=account_id, add=add)

    @classmethod
    def get_authenticated_user(cls) -> str | None:
        return get_user_email()

    @classmethod
    def list_accounts(cls) -> list[ConnectorAccount]:
        return [
            ConnectorAccount(
                account_id=str(account["account_id"]),
                label=str(account["label"]),
                auth_group=cls.auth_label or cls.source,
                source=cls.source,
                user_id=account.get("email"),
                email=account.get("email"),
            )
            for account in list_google_accounts()
        ]

    @classmethod
    async def verify_auth(cls, account_id: str | None = None) -> tuple[str, str | None]:
        import asyncio
        return await asyncio.to_thread(verify_google_auth, account_id)

    @classmethod
    def current_user_ids(cls) -> list[str]:
        return [str(account["email"]) for account in list_google_accounts() if account.get("email")]

    def can_handle(self, url: str) -> bool:
        return "mail.google.com" in url

    def entity_url(self, platform_entity_id: str) -> str | None:
        return f"https://mail.google.com/mail/u/0/#all/{platform_entity_id}"

    async def ingest(self, account_id: str | None = None) -> EntityBatch:
        import asyncio

        loop = asyncio.get_event_loop()
        service = await loop.run_in_executor(None, _build_service_for, account_id)
        after_date = (datetime.now(UTC) - timedelta(days=self.sync_horizon_days)).strftime("%Y/%m/%d")
        q = f"after:{after_date} -in:spam -in:trash"
        logger.info("gmail ingest: fetching all threads (query: %s)", q)
        batch = await _list_threads(service, loop, q, account_id=account_id)
        logger.info("gmail ingest: fetched %d thread(s)", len(batch.entities))
        return batch

    async def fetch(
        self,
        resource_type: ResourceType,
        resource_id: str,
        meta: dict[str, str] | None = None,
        account_id: str | None = None,
    ) -> EntityBatch:
        selected_account_id = account_id or ((meta or {}).get("account_id") if meta else None)
        if resource_type != "thread":
            logger.debug("gmail connector: unsupported resource_type %r — skipping", resource_type)
            return EntityBatch()

        gmail_message_id = (meta or {}).get("gmail_message_id")
        if gmail_message_id:
            # Content script extracted the hex message ID from the DOM — use it
            # to fetch the exact thread via the API.
            logger.info("gmail: fetching specific thread via message ID %s", gmail_message_id)
            batch = await _fetch_thread_by_message_id(gmail_message_id, account_id=selected_account_id)
            await upsert_batch(batch)
            return batch

        if resource_id and _GMAIL_THREAD_ID_RE.fullmatch(resource_id):
            # Caller supplied a Gmail API thread ID (hex) — fetch directly.
            logger.info("gmail: fetching specific thread by thread ID %s", resource_id)
            batch = await _fetch_thread_by_thread_id(resource_id, account_id=selected_account_id)
            await upsert_batch(batch)
            return batch

        logger.debug("gmail: no usable thread ID in resource_id=%r meta=%r — skipping", resource_id, meta)
        return EntityBatch()

    async def poll(
        self,
        cursor: dict[str, Any],
        account_id: str | None = None,
    ) -> tuple[EntityBatch, dict[str, Any]]:
        import asyncio

        loop = asyncio.get_event_loop()
        service = await loop.run_in_executor(None, _build_service_for, account_id)

        if not cursor:
            # First run: capture current historyId *before* bulk fetch so we don't miss
            # any messages that arrive during the bulk ingest.
            profile: dict[str, Any] = await loop.run_in_executor(
                None,
                lambda: service.users().getProfile(userId="me").execute(),
            )
            history_id: str = profile["historyId"]
            logger.info("gmail poll: initialised cursor at historyId %s; starting bulk ingest", history_id)

            after_date = (datetime.now(UTC) - timedelta(days=self.sync_horizon_days)).strftime("%Y/%m/%d")
            bulk_batch = await _list_threads(service, loop, f"in:inbox after:{after_date}", account_id=account_id)
            logger.info("gmail poll: bulk ingest fetched %d thread(s)", len(bulk_batch.entities))
            return bulk_batch, {"history_id": history_id}

        # Incremental poll via history list.
        # No labelId filter: we want replies to any thread already in the graph,
        # not just new inbox messages.
        start_history_id: str = cursor["history_id"]
        all_thread_ids: set[str] = set()
        inbox_thread_ids: set[str] = set()
        page_token: str | None = None
        latest_history_id = start_history_id

        while True:
            kwargs: dict[str, Any] = {
                "userId": "me",
                "startHistoryId": start_history_id,
                "historyTypes": ["messageAdded"],
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
                    msg = msg_added["message"]
                    tid = msg["threadId"]
                    all_thread_ids.add(tid)
                    if "INBOX" in msg.get("labelIds", []):
                        inbox_thread_ids.add(tid)

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        # Always fetch inbox threads (new conversations).
        # For non-inbox threads, only re-fetch those already in the graph
        # (replies to archived/sent threads the user has previously viewed).
        known_thread_ids = await _get_known_thread_ids(all_thread_ids - inbox_thread_ids)
        thread_ids = inbox_thread_ids | known_thread_ids

        logger.info(
            "gmail poll: %d inbox + %d known non-inbox thread(s)",
            len(inbox_thread_ids), len(known_thread_ids),
        )
        combined = EntityBatch()
        for tid in thread_ids:
            try:
                batch = await _fetch_thread_by_thread_id(tid, account_id=account_id)
                combined.entities.extend(batch.entities)
                combined.persons.extend(batch.persons)
                combined.edges.extend(batch.edges)
            except Exception:
                logger.exception("gmail poll: failed to fetch thread %s", tid)

        return combined, {"history_id": latest_history_id}


async def _fetch_thread_by_thread_id(thread_id: str, account_id: str | None = None) -> EntityBatch:
    """Fetch a thread directly by its Gmail thread ID."""
    import asyncio

    loop = asyncio.get_event_loop()
    service = await loop.run_in_executor(None, _build_service_for, account_id)

    thread: dict[str, Any] = await loop.run_in_executor(
        None,
        lambda: service.users().threads().get(
            userId="me", id=thread_id, format="full"
        ).execute(),
    )
    entity, persons, edges = _thread_to_items(thread, account_id=account_id)
    if not entity:
        return EntityBatch()
    batch = EntityBatch(entities=[entity], persons=persons, edges=edges)
    batch.add_stubs_from(entity)
    return batch


async def _fetch_thread_by_message_id(message_id: str, account_id: str | None = None) -> EntityBatch:
    """Fetch the thread containing a specific message, identified by its hex API message ID."""
    import asyncio

    loop = asyncio.get_event_loop()
    service = await loop.run_in_executor(None, _build_service_for, account_id)

    # Resolve message → thread ID
    msg: dict[str, Any] = await loop.run_in_executor(
        None,
        lambda: service.users().messages().get(
            userId="me", id=message_id, format="minimal"
        ).execute(),
    )
    thread_id: str = msg["threadId"]
    return await _fetch_thread_by_thread_id(thread_id, account_id=account_id)


def _thread_to_items(
    thread: dict[str, Any],
    account_id: str | None = None,
) -> tuple[EntityRecord | None, list[PersonRecord], list[EdgeRecord]]:
    """Convert a Gmail thread (full format) into graph items."""
    messages: list[dict[str, Any]] = thread.get("messages", [])
    if not messages:
        return None, [], []

    thread_id: str = thread["id"]

    first_headers = messages[0].get("payload", {}).get("headers", [])
    subject = _get_header(first_headers, "Subject") or "(no subject)"

    thread_created_at: datetime | None = None
    import contextlib
    with contextlib.suppress(Exception):
        thread_created_at = parsedate_to_datetime(_get_header(first_headers, "Date"))

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
        created_at=thread_created_at,
        updated_at=datetime.now(UTC),
        metadata={
            "message_count": len(messages),
            "snippet": thread.get("snippet", ""),
            "label_ids": ",".join(label_ids),
            **({"account_id": account_id} if account_id else {}),
        },
    )
    return entity, persons, edges


async def _list_threads(
    service: Any,
    loop: Any,
    q: str,
    account_id: str | None = None,
) -> EntityBatch:
    """Page through threads matching query q and return a combined EntityBatch."""
    combined = EntityBatch()
    page_token: str | None = None
    fetched = 0

    while True:
        kwargs: dict[str, Any] = {"userId": "me", "maxResults": 500, "q": q}
        if page_token:
            kwargs["pageToken"] = page_token

        response: dict[str, Any] = await loop.run_in_executor(
            None,
            lambda kw=kwargs: service.users().threads().list(**kw).execute(),
        )

        stubs = response.get("threads", [])
        total_estimate = response.get("resultSizeEstimate", "?")
        for thread_stub in stubs:
            try:
                batch = await _fetch_thread_by_thread_id(thread_stub["id"], account_id=account_id)
                combined.entities.extend(batch.entities)
                combined.persons.extend(batch.persons)
                combined.edges.extend(batch.edges)
                fetched += 1
                if fetched % 10 == 0:
                    logger.info("gmail ingest: %d / ~%s threads fetched", fetched, total_estimate)
            except Exception:
                logger.exception("gmail ingest: failed to fetch thread %s", thread_stub["id"])

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return combined


async def _get_known_thread_ids(thread_ids: set[str]) -> set[str]:
    """Return the subset of thread_ids already stored as gmail Thread entities."""
    from agentgraph.core.context import get_backend

    backend = get_backend()
    known: set[str] = set()
    for tid in thread_ids:
        if await backend.get_entity_by_platform("gmail", tid) is not None:
            known.add(tid)
    return known
