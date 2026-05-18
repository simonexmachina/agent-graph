"""Drive Changes connector — polls the Drive Changes API and dispatches to per-file connectors."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

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

logger = logging.getLogger(__name__)

_GDRIVE_FILE_MEDIA_URL = "https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
_GDRIVE_DOC_EXPORT_URL = "https://www.googleapis.com/drive/v3/files/{file_id}/export?mimeType=text/html"
_GDRIVE_DOC_EXPORT_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_GDRIVE_SHEET_EXPORT_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_GDRIVE_SHEET_EXPORT_URL = (
    "https://www.googleapis.com/drive/v3/files/{file_id}/export?"
    f"mimeType={_GDRIVE_SHEET_EXPORT_MIME}"
)
_MIME_EXTENSIONS: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.google-apps.document": ".docx",
    "application/vnd.google-apps.spreadsheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/html": ".html",
    "text/plain": ".txt",
}


def _build_drive_service() -> Any:
    return build("drive", "v3", credentials=google_credentials())


class DriveChangesConnector(BaseConnector):
    """Polls drive.changes.list and handles folder fetches."""

    source = "gdrive"
    fetch_policy = FetchPolicy(stale_after_seconds=15 * 60)
    poll_interval: timedelta | None = timedelta(minutes=10)  # type: ignore[assignment]
    poll_delegates = ["gdocs", "gsheets"]
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
        return (
            "drive.google.com/drive/folders/" in url
            or "drive.google.com/file/d/" in url
            or "docs.google.com/file/d/" in url
        )

    def entity_url(self, platform_entity_id: str) -> str | None:
        return f"https://drive.google.com/drive/folders/{platform_entity_id}"

    async def fetch(self, resource_type: ResourceType, resource_id: str, meta: dict[str, str] | None = None) -> EntityBatch:
        import asyncio

        from agentgraph.graph.upsert import upsert_batch

        loop = asyncio.get_event_loop()
        if resource_type == "folder":
            batch = await loop.run_in_executor(None, _list_drive_folder_sync, resource_id)
            await upsert_batch(batch)
            return batch

        batch = await _fetch_drive_file(resource_id)
        if batch.entities or batch.persons or batch.edges:
            await upsert_batch(batch)
        return batch

    async def download(
        self,
        resource_type: ResourceType,
        resource_id: str,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        if resource_type == "folder":
            raise ValueError("Drive folders cannot be downloaded as a single file")
        return await download_drive_file(resource_id, output_path)

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
        metadata=_file_metadata(
            web_url=f"https://drive.google.com/drive/folders/{folder_id}",
            mime_type="application/vnd.google-apps.folder",
        ),
    )

    stubs: list[EntityRecord] = []
    edges: list[EdgeRecord] = []

    for child in children:
        child_id: str = child["id"]
        child_name: str = child.get("name", "")
        mime: str = child.get("mimeType", "")
        web_link: str = child.get("webViewLink", "")
        download_link = _download_url_for_mime(child_id, mime)

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
            metadata=_file_metadata(
                web_url=web_link or _web_url_for_file(child_id),
                download_url=download_link,
                mime_type=mime or None,
            ),
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
    """Return the subset of file_ids that already exist in a Drive-backed connector."""
    from agentgraph.core.context import get_backend

    backend = get_backend()
    known: set[str] = set()
    for file_id in file_ids:
        for platform in ("gdocs", "gsheets", "gdrive"):
            result = await backend.get_entity_by_platform(platform, file_id)
            if result is not None:
                known.add(file_id)
                break
    return known


async def _fetch_drive_file(file_id: str) -> EntityBatch:
    import asyncio

    loop = asyncio.get_event_loop()
    service = await loop.run_in_executor(None, _build_drive_service)

    try:
        file_meta: dict[str, Any] = await loop.run_in_executor(
            None,
            lambda: service.files().get(
                fileId=file_id,
                fields="id,name,mimeType,owners,webViewLink,webContentLink",
            ).execute(),
        )
    except HttpError as exc:
        if exc.resp.status == 404:
            raise ValueError(f"Drive file not found or not accessible: {file_id}") from exc
        raise

    mime_type: str = file_meta.get("mimeType", "")
    if mime_type == "application/vnd.google-apps.folder":
        return await loop.run_in_executor(None, _list_drive_folder_sync, file_id)

    if mime_type == "application/vnd.google-apps.document":
        from agentgraph.connectors.registry import get_connector

        connector = get_connector("gdocs")
        if connector is not None:
            return await connector.fetch("document", file_id)

    if mime_type == "application/vnd.google-apps.spreadsheet":
        from agentgraph.connectors.registry import get_connector

        connector = get_connector("gsheets")
        if connector is not None:
            return await connector.fetch("spreadsheet", file_id)

    title: str = file_meta.get("name", "")
    web_link: str = file_meta.get("webViewLink") or _web_url_for_file(file_id)
    download_link: str = file_meta.get("webContentLink") or _download_url_for_mime(file_id, mime_type)

    edges: list[EdgeRecord] = []

    owner_persons: list[PersonRecord] = []
    for owner in file_meta.get("owners", []):
        email: str = owner.get("emailAddress", "")
        name: str = owner.get("displayName", "")
        if email:
            owner_persons.append(PersonRecord(
                platform="gdrive",
                platform_user_id=email,
                canonical_email=email,
                display_name=name or None,
            ))
            edges.append(EdgeRecord(
                edge_type="authored",
                source_platform_user_id=email,
                target_platform_entity_id=file_id,
                platform="gdrive",
            ))

    entity = EntityRecord(
        entity_type="Document",
        platform="gdrive",
        platform_entity_id=file_id,
        title=title,
        metadata=_file_metadata(
            web_url=web_link,
            download_url=download_link,
            mime_type=mime_type or None,
        ),
    )

    batch = EntityBatch(entities=[entity], persons=owner_persons, edges=edges)
    batch.add_stubs_from(entity)
    return batch


def _web_url_for_file(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view"


def _download_url_for_mime(file_id: str, mime_type: str) -> str:
    if mime_type == "application/vnd.google-apps.document":
        return _GDRIVE_DOC_EXPORT_URL.format(file_id=file_id)
    if mime_type == "application/vnd.google-apps.spreadsheet":
        return _GDRIVE_SHEET_EXPORT_URL.format(file_id=file_id)
    return _GDRIVE_FILE_MEDIA_URL.format(file_id=file_id)


def _file_metadata(
    *,
    web_url: str | None = None,
    download_url: str | None = None,
    mime_type: str | None = None,
) -> dict[str, str | int | float | bool | None]:
    metadata: dict[str, str | int | float | bool | None] = {}
    if web_url:
        metadata["web_url"] = web_url
    if download_url:
        metadata["download_url"] = download_url
    if mime_type:
        metadata["mime_type"] = mime_type
    return metadata


async def download_drive_file(file_id: str, output_path: str | None = None) -> dict[str, Any]:
    import asyncio
    import io

    from googleapiclient.http import MediaIoBaseDownload  # type: ignore[import-untyped]

    loop = asyncio.get_event_loop()
    service = await loop.run_in_executor(None, _build_drive_service)

    file_meta: dict[str, Any] = await loop.run_in_executor(
        None,
        lambda: service.files().get(
            fileId=file_id,
            fields="id,name,mimeType,size",
        ).execute(),
    )
    name: str = file_meta.get("name") or file_id
    mime_type: str = file_meta.get("mimeType", "")
    export_mime = _export_mime_for_download(mime_type)

    def _download() -> bytes:
        buf = io.BytesIO()
        if export_mime is not None:
            req = service.files().export(fileId=file_id, mimeType=export_mime)
        else:
            req = service.files().get_media(fileId=file_id)
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        return buf.getvalue()

    raw = await loop.run_in_executor(None, _download)
    target = _resolve_output_path(output_path, name, export_mime or mime_type)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)

    return {
        "path": str(target),
        "bytes": len(raw),
        "platform": "gdrive",
        "platform_entity_id": file_id,
        "filename": target.name,
        "mime_type": export_mime or mime_type,
    }


def _export_mime_for_download(mime_type: str) -> str | None:
    if mime_type == "application/vnd.google-apps.document":
        return _GDRIVE_DOC_EXPORT_MIME
    if mime_type == "application/vnd.google-apps.spreadsheet":
        return _GDRIVE_SHEET_EXPORT_MIME
    return None


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
