"""Gmail connector — ingests email threads as Email entities."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import base64
import logging
import re
from datetime import UTC, datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
from html import escape
from pathlib import Path
from typing import Any, cast

from googleapiclient.discovery import build  # type: ignore[import-untyped]

from agentgraph.connectors.base import (
    BaseConnector,
    ConnectorAccount,
    EdgeRecord,
    EntityBatch,
    EntityRecord,
    FetchPolicy,
    PersonRecord,
    ResourceType,
    SourceReference,
)
from agentgraph.graph.upsert import upsert_batch
from agentgraph_connector_google.provider import (
    get_credentials as google_credentials,
)
from agentgraph_connector_google.provider import (
    get_user_email,
    list_google_accounts,
    verify_google_auth,
)

logger = logging.getLogger(__name__)

_GMAIL_THREAD_URL_RE = re.compile(
    r"https://mail\.google\.com/mail/u/\d+/#[^/\s]+(?:/[^/\s]+)*/(?P<thread_id>[A-Za-z0-9_+=:/|-]{16,})"
)

_STALE_AFTER = 15 * 60

# Strip Re:/Fwd: prefixes for embedding but keep original as title
_SUBJECT_PREFIX_RE = re.compile(r"^(Re|Fwd|FW|RE|FWD):\s*", re.IGNORECASE)
# Gmail API thread/message IDs are lowercase hex strings (16 chars).
# URL hash fragments (legacy Gmail links) are base64-like and are NOT valid API IDs.
_GMAIL_THREAD_ID_RE = re.compile(r"[0-9a-f]{16,}")
_GMAIL_MESSAGE_ID_RE = re.compile(r"[0-9a-f]{16,}")
_ATTACHMENT_RESOURCE_PREFIX = "attachment"
_MIME_EXTENSIONS: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/html": ".html",
    "text/plain": ".txt",
}


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


def _extract_body(payload: dict[str, Any]) -> tuple[str, str]:
    """Recursively extract a MIME body, preferring the original HTML part."""

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
        return "\n".join(html_parts).strip(), "text/html"
    return "\n".join(text_parts).strip(), "text/plain"


def _decode_urlsafe_data(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _attachment_resource_id(message_id: str, attachment_id: str) -> str:
    return f"{_ATTACHMENT_RESOURCE_PREFIX}/{message_id}/{attachment_id}"


def _parse_attachment_resource_id(resource_id: str) -> tuple[str, str] | None:
    parts = resource_id.split("/", 2)
    if len(parts) != 3 or parts[0] != _ATTACHMENT_RESOURCE_PREFIX:
        return None
    _, message_id, attachment_id = parts
    if not message_id or not attachment_id:
        return None
    return message_id, attachment_id


def _resolve_output_path(output_path: str | None, name: str, mime_type: str) -> Path:
    if output_path is not None:
        path = Path(output_path).expanduser()
        if path.exists() and path.is_dir():
            return path / _filename_with_extension(name, mime_type)
        if output_path.endswith(("/", "\\")):
            return path / _filename_with_extension(name, mime_type)
        return path
    return Path.cwd() / _filename_with_extension(name, mime_type)


def _filename_with_extension(name: str, mime_type: str) -> str:
    suffix = _MIME_EXTENSIONS.get(mime_type)
    if suffix is None or Path(name).suffix:
        return name
    return f"{name}{suffix}"


def _part_header(part: dict[str, Any], name: str) -> str:
    return _get_header(cast(list[dict[str, str]], part.get("headers", [])), name)


def _is_downloadable_attachment_part(part: dict[str, Any]) -> bool:
    body = part.get("body") or {}
    attachment_id = body.get("attachmentId")
    filename = str(part.get("filename") or "")
    if not isinstance(attachment_id, str) or not attachment_id or not filename:
        return False

    disposition = _part_header(part, "Content-Disposition").lower()
    if disposition.startswith("inline") or _part_header(part, "Content-ID"):
        return False
    return disposition.startswith("attachment") or not disposition


def _extract_attachments(
    payload: dict[str, Any],
    message_id: str,
    thread_id: str,
    account_id: str | None = None,
) -> list[EntityRecord]:
    """Return Document stubs for Gmail MIME parts with attachment IDs."""
    attachments: list[EntityRecord] = []

    def _collect(part: dict[str, Any]) -> None:
        body = part.get("body") or {}
        attachment_id = body.get("attachmentId")
        filename = str(part.get("filename") or "")
        if _is_downloadable_attachment_part(part) and isinstance(attachment_id, str):
            resource_id = _attachment_resource_id(message_id, attachment_id)
            metadata: dict[str, str | int | float | bool | None] = {
                "gmail_thread_id": thread_id,
                "gmail_message_id": message_id,
                "gmail_attachment_id": attachment_id,
                "web_url": f"https://mail.google.com/mail/u/0/#all/{thread_id}",
            }
            mime_type = part.get("mimeType")
            if isinstance(mime_type, str) and mime_type:
                metadata["mime_type"] = mime_type
            size = body.get("size")
            if isinstance(size, int):
                metadata["size"] = size
            if filename:
                metadata["filename"] = filename
            if account_id:
                metadata["account_id"] = account_id
            attachments.append(
                EntityRecord(
                    entity_type="Document",
                    platform="gmail",
                    platform_entity_id=resource_id,
                    title=filename or attachment_id,
                    metadata=metadata,
                    is_stub=True,
                )
            )
        for child in part.get("parts", []):
            _collect(child)

    _collect(payload)
    return attachments


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
    auth_description = "Gmail conversations (last 90 days by default): Email entities containing full message bodies with senders, recipients, and cc participants."
    auth_label = "google"

    @classmethod
    def run_auth_flow(
        cls,
        account_id: str | None = None,
        add: bool = False,
        args: list[str] | None = None,
    ) -> None:
        from agentgraph_connector_google.auth import run_oauth_flow

        run_oauth_flow(account_id=account_id, add=add, args=args)

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
        return self.resolve_url(url) is not None

    def resolve_url(self, url: str) -> SourceReference | None:
        match = _GMAIL_THREAD_URL_RE.search(url)
        if match is None:
            return None
        return SourceReference(
            source=self.source,
            resource_type="thread",
            resource_id=match.group("thread_id"),
        )

    def entity_url(self, platform_entity_id: str) -> str | None:
        return f"https://mail.google.com/mail/u/0/#all/{platform_entity_id}"

    async def ingest(self, account_id: str | None = None) -> EntityBatch:
        import asyncio

        loop = asyncio.get_event_loop()
        service = await loop.run_in_executor(None, _build_service_for, account_id)
        after_date = (datetime.now(UTC) - timedelta(days=self.sync_horizon_days)).strftime(
            "%Y/%m/%d"
        )
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
        if gmail_message_id and _GMAIL_MESSAGE_ID_RE.fullmatch(gmail_message_id):
            # Content script extracted the hex message ID from the DOM — use it
            # to fetch the exact thread via the API.
            logger.info("gmail: fetching specific thread via message ID %s", gmail_message_id)
            batch = await _fetch_thread_by_message_id(
                gmail_message_id,
                account_id=selected_account_id,
            )
            await upsert_batch(batch)
            return batch

        gmail_thread_id = (meta or {}).get("gmail_thread_id")
        if gmail_thread_id and _GMAIL_THREAD_ID_RE.fullmatch(gmail_thread_id):
            # Content script extracted the legacy hex thread ID from the DOM.
            logger.info("gmail: fetching specific thread via meta thread ID %s", gmail_thread_id)
            batch = await _fetch_thread_by_thread_id(
                gmail_thread_id,
                account_id=selected_account_id,
            )
            await upsert_batch(batch)
            return batch

        if resource_id and _GMAIL_THREAD_ID_RE.fullmatch(resource_id):
            # Caller supplied a Gmail API thread ID (hex) — fetch directly.
            logger.info("gmail: fetching specific thread by thread ID %s", resource_id)
            batch = await _fetch_thread_by_thread_id(
                resource_id,
                account_id=selected_account_id,
            )
            await upsert_batch(batch)
            return batch

        logger.debug(
            "gmail: no usable thread ID in resource_id=%r meta=%r — skipping", resource_id, meta
        )
        return EntityBatch()

    async def download(
        self,
        resource_type: ResourceType,
        resource_id: str,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Download a Gmail attachment Document stub using stored Google auth."""
        if resource_type != "document":
            raise NotImplementedError(f"{self.source} only downloads attachment document stubs")

        parsed = _parse_attachment_resource_id(resource_id)
        if parsed is None:
            raise NotImplementedError(f"{self.source} can only download attachment document stubs")
        message_id, attachment_id = parsed

        metadata: dict[str, Any] = {}
        from agentgraph.core.context import get_backend

        entity = await get_backend().get_entity_by_platform(self.source, resource_id)
        if entity is not None and isinstance(entity.get("metadata"), dict):
            metadata = cast(dict[str, Any], entity["metadata"])

        account_id = metadata.get("account_id")
        selected_account_id = account_id if isinstance(account_id, str) else None
        filename = metadata.get("filename")
        name = filename if isinstance(filename, str) and filename else attachment_id
        mime_value = metadata.get("mime_type")
        mime_type = mime_value if isinstance(mime_value, str) else "application/octet-stream"

        import asyncio

        loop = asyncio.get_event_loop()
        service = await loop.run_in_executor(None, _build_service_for, selected_account_id)
        response: dict[str, Any] = await loop.run_in_executor(
            None,
            lambda: (
                service.users()
                .messages()
                .attachments()
                .get(
                    userId="me",
                    messageId=message_id,
                    id=attachment_id,
                )
                .execute()
            ),
        )
        data = response.get("data")
        if not isinstance(data, str):
            raise ValueError(f"Attachment {attachment_id!r} returned no data")

        raw = _decode_urlsafe_data(data)
        target = _resolve_output_path(output_path, name, mime_type)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)

        return {
            "path": str(target),
            "bytes": len(raw),
            "platform": "gmail",
            "platform_entity_id": resource_id,
            "filename": Path(target).name,
            "mime_type": mime_type,
        }

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
            logger.info(
                "gmail poll: initialised cursor at historyId %s; starting bulk ingest", history_id
            )

            after_date = (datetime.now(UTC) - timedelta(days=self.sync_horizon_days)).strftime(
                "%Y/%m/%d"
            )
            bulk_batch = await _list_threads(
                service, loop, f"in:inbox after:{after_date}", account_id=account_id
            )
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
            len(inbox_thread_ids),
            len(known_thread_ids),
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


async def _fetch_thread_by_thread_id(
    thread_id: str,
    account_id: str | None = None,
) -> EntityBatch:
    """Fetch a thread directly by its Gmail thread ID."""
    import asyncio

    loop = asyncio.get_event_loop()
    service = await loop.run_in_executor(None, _build_service_for, account_id)

    thread: dict[str, Any] = await loop.run_in_executor(
        None,
        lambda: service.users().threads().get(userId="me", id=thread_id, format="full").execute(),
    )
    entity, persons, edges, attachment_stubs = _thread_to_items(thread, account_id=account_id)
    if not entity:
        return EntityBatch()
    batch = EntityBatch(entities=[entity, *attachment_stubs], persons=persons, edges=edges)
    batch.add_stubs_from(entity)
    return batch


async def _fetch_thread_by_message_id(
    message_id: str,
    account_id: str | None = None,
) -> EntityBatch:
    """Fetch the thread containing a specific message, identified by its hex API message ID."""
    import asyncio

    loop = asyncio.get_event_loop()
    service = await loop.run_in_executor(None, _build_service_for, account_id)

    # Resolve message → thread ID
    msg: dict[str, Any] = await loop.run_in_executor(
        None,
        lambda: (
            service.users().messages().get(userId="me", id=message_id, format="minimal").execute()
        ),
    )
    thread_id: str = msg["threadId"]
    return await _fetch_thread_by_thread_id(thread_id, account_id=account_id)


def _thread_to_items(
    thread: dict[str, Any],
    account_id: str | None = None,
) -> tuple[EntityRecord | None, list[PersonRecord], list[EdgeRecord], list[EntityRecord]]:
    """Convert a Gmail thread (full format) into graph items."""
    messages: list[dict[str, Any]] = thread.get("messages", [])
    if not messages:
        return None, [], [], []

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
    attachment_stubs: list[EntityRecord] = []
    seen_emails: set[str] = set()
    first_sender_email: str | None = None

    for msg in messages:
        message_id = str(msg.get("id") or "")
        payload = msg.get("payload", {})
        headers = payload.get("headers", [])

        from_header = _get_header(headers, "From")
        to_header = _get_header(headers, "To")
        cc_header = _get_header(headers, "Cc")
        date_header = _get_header(headers, "Date")

        body, body_content_type = _extract_body(payload)
        if message_id:
            new_attachments = _extract_attachments(
                payload,
                message_id=message_id,
                thread_id=thread_id,
                account_id=account_id,
            )
            attachment_stubs.extend(new_attachments)
            for attachment in new_attachments:
                edges.append(
                    EdgeRecord(
                        edge_type="references",
                        source_platform_entity_id=thread_id,
                        target_platform_entity_id=attachment.platform_entity_id,
                        platform="gmail",
                    )
                )

        block_lines = [
            "<p>",
            f"<strong>From:</strong> {escape(from_header)}<br>",
            f"<strong>Date:</strong> {escape(_format_date(date_header))}",
        ]
        if to_header:
            block_lines.append(f"<br><strong>To:</strong> {escape(to_header)}")
        block_lines.append("</p>")
        if body_content_type == "text/html":
            block_lines.append(body or "<p><em>(empty)</em></p>")
        else:
            block_lines.append(f"<pre>{escape(body or '(empty)')}</pre>")
        content_blocks.append("\n".join(block_lines))

        for display_name, email in _parse_email_addresses(f"{from_header},{to_header},{cc_header}"):
            if email in seen_emails:
                continue
            seen_emails.add(email)
            persons.append(
                PersonRecord(
                    platform="gmail",
                    platform_user_id=email,
                    canonical_email=email,
                    display_name=display_name or None,
                )
            )
            if first_sender_email is None:
                _, sender_addr = parseaddr(from_header)
                if sender_addr.lower() == email:
                    first_sender_email = email

    content = "\n<hr>\n".join(content_blocks)

    for email in seen_emails:
        edge_type = "authored" if email == first_sender_email else "participated_in"
        edges.append(
            EdgeRecord(
                edge_type=edge_type,
                source_platform_user_id=email,
                target_platform_entity_id=thread_id,
                platform="gmail",
            )
        )

    label_ids: list[str] = messages[0].get("labelIds", [])
    entity = EntityRecord(
        entity_type="Email",
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
            "content_type": "text/html",
            **({"account_id": account_id} if account_id else {}),
        },
    )
    return entity, persons, edges, attachment_stubs


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

        def _list_threads_page(request_kwargs: dict[str, Any] = kwargs) -> dict[str, Any]:
            return cast(dict[str, Any], service.users().threads().list(**request_kwargs).execute())

        response: dict[str, Any] = await loop.run_in_executor(
            None,
            _list_threads_page,
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
    """Return the subset of thread IDs already stored as Gmail Email entities."""
    from agentgraph.core.context import get_backend

    backend = get_backend()
    known: set[str] = set()
    for tid in thread_ids:
        if await backend.get_entity_by_platform("gmail", tid) is not None:
            known.add(tid)
    return known
