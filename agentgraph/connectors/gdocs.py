"""Google Docs connector."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from google.auth.transport.requests import Request  # type: ignore[import-untyped]
from google.oauth2.credentials import Credentials  # type: ignore[import-untyped]
from googleapiclient.discovery import build  # type: ignore[import-untyped]

from agentgraph.auth.credentials import load as load_creds
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

# Staleness: re-fetch if doc hasn't been synced in the last 15 minutes
_STALE_AFTER = 15 * 60


def _build_service() -> Any:
    stored = load_creds()
    if stored.google is None:
        raise RuntimeError("Google credentials not configured. Run: agentgraph auth google-docs")

    g = stored.google
    creds = Credentials(
        token=g.access_token,
        refresh_token=g.refresh_token,
        token_uri=g.token_uri,
        client_id=g.client_id,
        client_secret=g.client_secret,
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Persist refreshed token
        from agentgraph.auth.credentials import GoogleCredentials, update
        update("google", GoogleCredentials(
            client_id=g.client_id,
            client_secret=g.client_secret,
            access_token=creds.token or "",
            refresh_token=creds.refresh_token or "",
        ))

    return build("docs", "v1", credentials=creds)


def _extract_plain_text(doc: dict[str, Any]) -> str:
    """Walk the document body and extract plain text."""
    parts: list[str] = []
    body = doc.get("body", {})
    for element in body.get("content", []):
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        for pe in paragraph.get("elements", []):
            text_run = pe.get("textRun")
            if text_run:
                parts.append(text_run.get("content", ""))
    return "".join(parts).strip()


def _extract_persons(doc: dict[str, Any], doc_id: str) -> tuple[list[PersonRecord], list[EdgeRecord]]:
    """Extract collaborators from suggestions and comments as Person records."""
    persons: list[PersonRecord] = []
    edges: list[EdgeRecord] = []
    seen_emails: set[str] = set()

    # Owner from revisionId / named styles isn't easily available via Docs API alone.
    # We pull suggested changes authors and comment authors as collaborators.
    for suggestion in doc.get("suggestedDocumentStyleChanges", {}).values():
        author = suggestion.get("author", {})
        email = author.get("email", "")
        name = author.get("displayName", "")
        if email and email not in seen_emails:
            seen_emails.add(email)
            persons.append(PersonRecord(
                platform="gdocs",
                platform_user_id=email,
                canonical_email=email,
                display_name=name or None,
            ))
            edges.append(EdgeRecord(
                edge_type="collaborated",
                source_platform_user_id=email,
                target_platform_entity_id=doc_id,
                platform="gdocs",
            ))

    return persons, edges


class GoogleDocsConnector(BaseConnector):
    source = "gdocs"
    fetch_policy = FetchPolicy(stale_after_seconds=_STALE_AFTER)

    def can_handle(self, url: str) -> bool:
        return "docs.google.com/document" in url

    async def fetch(self, resource_type: str, resource_id: str) -> EntityBatch:
        last_sync = await self.last_synced_at(resource_id)
        decision = self.fetch_policy.decide(last_sync)

        if decision == FetchPolicy.FRESH:
            logger.debug("gdocs/%s is fresh — updating last_accessed only", resource_id)
            await _touch_last_accessed(resource_id)
            return EntityBatch()

        logger.info("Fetching Google Doc %s (policy=%s)", resource_id, decision)
        batch = await _fetch_doc(resource_id)
        await upsert_batch(batch)
        return batch


async def _touch_last_accessed(doc_id: str) -> None:
    from agentgraph.db.connection import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:  # type: ignore[attr-defined]
        await conn.execute(  # type: ignore[attr-defined]
            "UPDATE entities SET last_accessed = now() WHERE platform = 'gdocs' AND platform_entity_id = $1",
            doc_id,
        )


async def _fetch_doc(doc_id: str) -> EntityBatch:
    import asyncio

    service = await asyncio.get_event_loop().run_in_executor(None, _build_service)
    doc: dict[str, Any] = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: service.documents().get(documentId=doc_id).execute(),
    )

    title = doc.get("title", "")
    content = _extract_plain_text(doc)
    persons, person_edges = _extract_persons(doc, doc_id)

    entity = EntityRecord(
        entity_type="Document",
        platform="gdocs",
        platform_entity_id=doc_id,
        title=title,
        content=content,
        updated_at=datetime.now(timezone.utc),
    )

    return EntityBatch(
        entities=[entity],
        persons=persons,
        edges=person_edges,
    )
