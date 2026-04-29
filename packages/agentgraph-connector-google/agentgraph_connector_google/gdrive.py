"""Drive Changes connector — polls the Drive Changes API and dispatches to per-file connectors."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from googleapiclient.discovery import build  # type: ignore[import-untyped]

from agentgraph.auth.google_provider import get_provider
from agentgraph.connectors.base import BaseConnector, EntityBatch, FetchPolicy, ResourceType

logger = logging.getLogger(__name__)

# Stub fetch_policy — DriveChangesConnector never handles direct fetches.
_STUB_POLICY = FetchPolicy(stale_after_seconds=0)


def _build_drive_service() -> Any:
    return build("drive", "v3", credentials=get_provider().get_credentials())


class DriveChangesConnector(BaseConnector):
    """Polls drive.changes.list and dispatches each changed file to the matching connector."""

    source = "drive"
    fetch_policy = _STUB_POLICY
    poll_interval: timedelta | None = timedelta(minutes=10)  # type: ignore[assignment]

    def can_handle(self, url: str) -> bool:
        # DriveChangesConnector is a coordinator — it never handles direct URL fetches.
        return False

    async def fetch(self, resource_type: ResourceType, resource_id: str, meta: dict[str, str] | None = None) -> EntityBatch:
        return EntityBatch()

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


async def _get_known_file_ids(file_ids: set[str]) -> set[str]:
    """Return the subset of file_ids that already exist in the entities table."""
    from agentgraph.db.connection import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT platform_entity_id FROM entities
            WHERE platform IN ('gdocs', 'gsheets') AND platform_entity_id = ANY($1)
            """,
            list(file_ids),
        )
    return {row["platform_entity_id"] for row in rows}
