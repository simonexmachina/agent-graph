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

from agentgraph.auth.google_provider import get_credentials as google_credentials
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
    return build("drive", "v3", credentials=google_credentials())


def _web_url(doc_id: str) -> str:
    return f"https://docs.google.com/document/d/{doc_id}/view"


def _download_url(doc_id: str) -> str:
    return f"https://www.googleapis.com/drive/v3/files/{doc_id}/export?mimeType=text/html"


def _metadata(doc_id: str) -> dict[str, str | int | float | bool | None]:
    return {
        "web_url": _web_url(doc_id),
        "download_url": _download_url(doc_id),
        "mime_type": "text/html",
    }



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
    url_patterns = ["https://docs.google.com/document/*"]
    auth_label = "google"
    auth_description = "Google Docs: Document entities with full markdown-rendered body content and owner authorship."
    onboard_prompt = "Set up Google?"

    @classmethod
    def run_auth_flow(cls) -> None:
        from agentgraph_connector_google.auth import run_oauth_flow
        run_oauth_flow()

    @classmethod
    def get_authenticated_user(cls) -> str | None:
        from agentgraph.auth.google_provider import get_user_email
        return get_user_email()

    @classmethod
    async def verify_auth(cls) -> tuple[str, str | None]:
        import asyncio

        from agentgraph.auth.google_provider import verify_google_auth
        return await asyncio.to_thread(verify_google_auth)

    @classmethod
    def current_user_id(cls) -> str | None:
        from agentgraph.auth.google_provider import get_user_email
        return get_user_email()

    def can_handle(self, url: str) -> bool:
        return "docs.google.com/document" in url

    def entity_url(self, platform_entity_id: str) -> str | None:
        return f"https://docs.google.com/document/d/{platform_entity_id}"

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

    async def download(
        self,
        resource_type: ResourceType,
        resource_id: str,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        from agentgraph_connector_google.gdrive import download_drive_file

        return await download_drive_file(resource_id, output_path)


async def _touch_last_accessed(doc_id: str) -> None:
    from agentgraph.core.context import get_backend

    await get_backend().touch_last_accessed("gdocs", doc_id)


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
        metadata=_metadata(doc_id),
        updated_at=datetime.now(UTC),
    )

    batch = EntityBatch(entities=[entity], persons=persons, edges=edges)
    batch.add_stubs_from(entity)
    return batch
