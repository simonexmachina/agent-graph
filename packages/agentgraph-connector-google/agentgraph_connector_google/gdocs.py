"""Google Docs connector."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

import markdownify  # type: ignore[import-untyped]
from googleapiclient.discovery import build  # type: ignore[import-untyped]
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from agentgraph.auth.google_provider import (
    get_credentials as google_credentials,
)
from agentgraph.auth.google_provider import (
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
    SourceReference,
)
from agentgraph.graph.upsert import upsert_batch

logger = logging.getLogger(__name__)

_GDOCS_URL_RE = re.compile(
    r"https://docs\.google\.com/document/d/(?P<doc_id>[a-zA-Z0-9_-]+)"
)

# Staleness: re-fetch if doc hasn't been synced in the last 15 minutes
_STALE_AFTER = 15 * 60


def _build_drive_service(account_id: str | None = None) -> Any:
    return build("drive", "v3", credentials=google_credentials(account_id))


def _build_drive_service_for(account_id: str | None) -> Any:
    return _build_drive_service(account_id) if account_id is not None else _build_drive_service()


def _web_url(doc_id: str) -> str:
    return f"https://docs.google.com/document/d/{doc_id}/view"


def _download_url(doc_id: str) -> str:
    return f"https://www.googleapis.com/drive/v3/files/{doc_id}/export?mimeType=text/html"


def _metadata(doc_id: str, account_id: str | None = None) -> dict[str, str | int | float | bool | None]:
    meta: dict[str, str | int | float | bool | None] = {
        "web_url": _web_url(doc_id),
        "download_url": _download_url(doc_id),
        # The export is HTML, but _export_as_markdown stores Markdown in content.
        "content_type": "text/markdown",
        "mime_type": "text/html",
    }
    if account_id:
        meta["account_id"] = account_id
    return meta



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
        return self.resolve_url(url) is not None

    def resolve_url(self, url: str) -> SourceReference | None:
        match = _GDOCS_URL_RE.match(url)
        if match is None:
            return None
        return SourceReference(
            source=self.source,
            resource_type="document",
            resource_id=match.group("doc_id"),
        )

    def entity_url(self, platform_entity_id: str) -> str | None:
        return f"https://docs.google.com/document/d/{platform_entity_id}"

    async def fetch(
        self,
        resource_type: ResourceType,
        resource_id: str,
        meta: dict[str, str] | None = None,
        account_id: str | None = None,
    ) -> EntityBatch:
        last_sync = await self.last_synced_at(resource_id)
        decision = self.fetch_policy.decide(last_sync)

        if decision == FetchPolicy.FRESH:
            logger.debug("gdocs/%s is fresh — updating last_accessed only", resource_id)
            await _touch_last_accessed(resource_id)
            return EntityBatch()

        logger.info("Fetching Google Doc %s (policy=%s)", resource_id, decision)
        selected_account_id = account_id or ((meta or {}).get("account_id") if meta else None)
        batch = await _fetch_doc(resource_id, account_id=selected_account_id)
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


async def _fetch_doc(doc_id: str, account_id: str | None = None) -> EntityBatch:
    import asyncio

    loop = asyncio.get_event_loop()
    drive_service = await loop.run_in_executor(None, _build_drive_service_for, account_id)

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
        metadata=_metadata(doc_id, account_id),
        updated_at=datetime.now(UTC),
    )

    batch = EntityBatch(entities=[entity], persons=persons, edges=edges)
    batch.add_stubs_from(entity)
    return batch
