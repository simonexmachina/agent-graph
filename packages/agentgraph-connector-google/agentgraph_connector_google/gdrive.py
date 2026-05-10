"""Drive Changes connector — polls the Drive Changes API and dispatches to per-file connectors."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from googleapiclient.discovery import build  # type: ignore[import-untyped]

from agentgraph.auth.google_provider import get_credentials as google_credentials
from agentgraph.connectors.base import (
    BaseConnector,
    EdgeRecord,
    EntityBatch,
    EntityRecord,
    FetchPolicy,
    ResourceType,
)

logger = logging.getLogger(__name__)

def _build_drive_service() -> Any:
    return build("drive", "v3", credentials=google_credentials())


class DriveChangesConnector(BaseConnector):
    """Polls drive.changes.list and handles folder fetches."""

    source = "gdrive"
    fetch_policy = FetchPolicy(stale_after_seconds=15 * 60)
    poll_interval: timedelta | None = timedelta(minutes=10)  # type: ignore[assignment]
    url_patterns = ["https://drive.google.com/*", "https://docs.google.com/file/*"]
    auth_label = "google"
    auth_description = "Google Drive: Document entities for non-native files (PDFs, etc.) and Folder entities listing their contents; polls the Drive Changes API to keep gdocs and gsheets current."

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
        return "drive.google.com/drive/folders/" in url

    def entity_url(self, platform_entity_id: str) -> str | None:
        return f"https://drive.google.com/drive/folders/{platform_entity_id}"

    async def fetch(self, resource_type: ResourceType, resource_id: str, meta: dict[str, str] | None = None) -> EntityBatch:
        import asyncio

        from agentgraph.graph.upsert import upsert_batch

        loop = asyncio.get_event_loop()
        batch = await loop.run_in_executor(None, _list_drive_folder_sync, resource_id)
        await upsert_batch(batch)
        return batch

    async def poll(self, cursor: dict[str, Any]) -> tuple[EntityBatch, dict[str, Any]]:
        import asyncio

        loop = asyncio.get_event_loop()
        service = await loop.run_in_executor(None, _build_drive_service)

        if not cursor:
            # First run: record current start pageToken.
            response: dict[str, Any] = await loop.run_in_executor(
                None,
                lambda: service.changes().getStartPageToken().execute(),
            )
            page_token: str = response["startPageToken"]
            return EntityBatch(), {"page_token": page_token}

        page_token = cursor["page_token"]
        changed_files: list[dict[str, Any]] = []
        new_page_token = page_token

        while True:
            response = await loop.run_in_executor(
                None,
                lambda pt=page_token: service.changes().list(
                    pageToken=pt,
                    fields="nextPageToken,newStartPageToken,changes(fileId,removed,file(id,name,webViewLink,mimeType))",
                    spaces="drive",
                ).execute(),
            )

            for change in response.get("changes", []):
                if change.get("removed"):
                    continue
                file_info = change.get("file")
                if file_info and file_info.get("webViewLink"):
                    changed_files.append(file_info)

            if "newStartPageToken" in response:
                new_page_token = response["newStartPageToken"]
                break
            page_token = response.get("nextPageToken", page_token)

        combined = EntityBatch()
        if changed_files:
            from agentgraph.connectors.registry import get_all_connectors

            connectors = get_all_connectors()
            known_file_ids = await _get_known_file_ids({f["id"] for f in changed_files})

            for file_info in changed_files:
                file_id: str = file_info["id"]
                web_link: str = file_info["webViewLink"]

                if file_id not in known_file_ids:
                    continue

                connector = next((c for c in connectors if c.can_handle(web_link)), None)
                if connector is None:
                    continue

                try:
                    from agentgraph.server.router import classify_url

                    ref = classify_url(web_link)
                    if ref is None:
                        continue
                    batch = await connector.fetch(ref.resource_type, ref.resource_id)
                    combined.entities.extend(batch.entities)
                    combined.persons.extend(batch.persons)
                    combined.edges.extend(batch.edges)
                except Exception:
                    logger.exception("drive poll: failed to fetch %s via %s", file_id, connector.source)

        return combined, {"page_token": new_page_token}


_GDRIVE_MIME_TO_RESOURCE: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document":     ("gdocs",   "document"),
    "application/vnd.google-apps.spreadsheet":  ("gsheets", "spreadsheet"),
    "application/vnd.google-apps.folder":       ("gdrive",  "folder"),
}
_GDRIVE_VIEW_BASE = "https://drive.google.com"


def _list_drive_folder_sync(folder_id: str) -> EntityBatch:
    service = _build_drive_service()

    # Get folder metadata
    meta: dict[str, Any] = service.files().get(
        fileId=folder_id,
        fields="id,name",
    ).execute()
    folder_name: str = meta.get("name", "")

    # List immediate children (non-trashed)
    children: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "q": f"'{folder_id}' in parents and trashed=false",
            "fields": "nextPageToken,files(id,name,mimeType,webViewLink)",
            "pageSize": 1000,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        resp: dict[str, Any] = service.files().list(**kwargs).execute()
        children.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    folder_entity = EntityRecord(
        entity_type="Folder",
        platform="gdrive",
        platform_entity_id=folder_id,
        title=folder_name,
        metadata={},
    )

    stubs: list[EntityRecord] = []
    edges: list[EdgeRecord] = []

    for child in children:
        child_id: str = child["id"]
        child_name: str = child.get("name", "")
        mime: str = child.get("mimeType", "")
        web_link: str = child.get("webViewLink", "")

        if mime in _GDRIVE_MIME_TO_RESOURCE:
            platform, resource_type_str = _GDRIVE_MIME_TO_RESOURCE[mime]
        else:
            # Non-Google native file — stub as a generic document under gdrive
            platform = "gdrive"
            resource_type_str = "document"

        from agentgraph.connectors.base import RESOURCE_TYPE_TO_ENTITY_TYPE
        entity_type = RESOURCE_TYPE_TO_ENTITY_TYPE.get(resource_type_str, "Document")

        stubs.append(EntityRecord(
            entity_type=entity_type,
            platform=platform,
            platform_entity_id=child_id,
            title=child_name,
            metadata={"web_url": web_link, "mime_type": mime} if web_link else {"mime_type": mime},
            is_stub=True,
        ))
        edges.append(EdgeRecord(
            edge_type="contains",
            source_platform_entity_id=folder_id,
            target_platform_entity_id=child_id,
            platform="gdrive",
        ))

    logger.info("Listed %d items in Drive folder '%s' (%s)", len(stubs), folder_name, folder_id)
    return EntityBatch(entities=[folder_entity, *stubs], edges=edges)


async def _get_known_file_ids(file_ids: set[str]) -> set[str]:
    """Return the subset of file_ids that already exist as gdocs or gsheets entities."""
    from agentgraph.core.context import get_backend

    backend = get_backend()
    known: set[str] = set()
    for file_id in file_ids:
        for platform in ("gdocs", "gsheets"):
            result = await backend.get_entity_by_platform(platform, file_id)
            if result is not None:
                known.add(file_id)
                break
    return known
