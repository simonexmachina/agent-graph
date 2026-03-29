"""Google Docs connector."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import markdownify  # type: ignore[import-untyped]
from googleapiclient.discovery import build  # type: ignore[import-untyped]
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

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

# Staleness: re-fetch if doc hasn't been synced in the last 15 minutes
_STALE_AFTER = 15 * 60


def _build_drive_service() -> Any:
    return build("drive", "v3", credentials=get_provider().get_credentials())


def _export_as_markdown(drive_service: Any, doc_id: str) -> str:
    """Export a Google Doc as HTML via Drive and convert to Markdown."""
    html: bytes = drive_service.files().export(
        fileId=doc_id,
        mimeType="text/html",
    ).execute()
    return markdownify.markdownify(  # type: ignore[no-any-return]
        html.decode("utf-8", errors="replace"),
        heading_style="ATX",
        bullets="-",
    ).strip()


class GoogleDocsConnector(BaseConnector):
    source = "gdocs"
    fetch_policy = FetchPolicy(stale_after_seconds=_STALE_AFTER)

    def can_handle(self, url: str) -> bool:
        return "docs.google.com/document" in url

    async def fetch(self, resource_type: ResourceType, resource_id: str, meta: dict[str, str] | None = None) -> EntityBatch:
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

    loop = asyncio.get_event_loop()
    drive_service = await loop.run_in_executor(None, _build_drive_service)

    try:
        file_meta: dict[str, Any] = await loop.run_in_executor(
            None,
            lambda: drive_service.files().get(
                fileId=doc_id,
                fields="name,owners",
            ).execute(),
        )
    except HttpError as exc:
        if exc.resp.status == 404:
            raise ValueError(f"Google Doc not found or not accessible: {doc_id}") from exc
        raise

    title: str = file_meta.get("name", "")
    content = await loop.run_in_executor(None, _export_as_markdown, drive_service, doc_id)

    persons: list[PersonRecord] = []
    edges: list[EdgeRecord] = []

    for owner in file_meta.get("owners", []):
        email: str = owner.get("emailAddress", "")
        name: str = owner.get("displayName", "")
        if email:
            persons.append(PersonRecord(
                platform="gdocs",
                platform_user_id=email,
                canonical_email=email,
                display_name=name or None,
            ))
            edges.append(EdgeRecord(
                edge_type="authored",
                source_platform_user_id=email,
                target_platform_entity_id=doc_id,
                platform="gdocs",
            ))

    entity = EntityRecord(
        entity_type="Document",
        platform="gdocs",
        platform_entity_id=doc_id,
        title=title,
        content=content,
        updated_at=datetime.now(UTC),
    )

    batch = EntityBatch(entities=[entity], persons=persons, edges=edges)
    batch.add_stubs_from(entity)
    return batch
