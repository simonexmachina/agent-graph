"""Google Sheets connector."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import logging
from datetime import UTC, datetime
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


def _build_sheets_service() -> Any:
    return build("sheets", "v4", credentials=get_provider().get_credentials())


def _build_drive_service() -> Any:
    return build("drive", "v3", credentials=get_provider().get_credentials())


def _extract_plain_text(spreadsheet: dict[str, Any], values_by_range: dict[str, list[list[str]]]) -> str:
    """Render each sheet as a labelled table of tab-separated rows."""
    sections: list[str] = []
    for sheet in spreadsheet.get("sheets", []):
        props = sheet.get("properties", {})
        sheet_title: str = props.get("title", "Sheet")
        rows = values_by_range.get(sheet_title, [])
        if not rows:
            continue
        lines = [sheet_title, "-" * len(sheet_title)]
        for row in rows:
            line = "\t".join(str(cell) for cell in row)
            if line.strip():
                lines.append(line)
        if len(lines) > 2:  # has content beyond header
            sections.append("\n".join(lines))
    return "\n\n".join(sections).strip()


class GoogleSheetsConnector(BaseConnector):
    source = "gsheets"
    fetch_policy = FetchPolicy(stale_after_seconds=_STALE_AFTER)

    def can_handle(self, url: str) -> bool:
        return "docs.google.com/spreadsheets" in url

    async def fetch(self, resource_type: ResourceType, resource_id: str, meta: dict[str, str] | None = None) -> EntityBatch:
        last_sync = await self.last_synced_at(resource_id)
        decision = self.fetch_policy.decide(last_sync)

        if decision == FetchPolicy.FRESH:
            logger.debug("gsheets/%s is fresh — updating last_accessed only", resource_id)
            await _touch_last_accessed(resource_id)
            return EntityBatch()

        logger.info("Fetching Google Sheet %s (policy=%s)", resource_id, decision)
        batch = await _fetch_sheet(resource_id)
        await upsert_batch(batch)
        return batch


async def _touch_last_accessed(spreadsheet_id: str) -> None:
    from agentgraph.db.connection import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:  # type: ignore[attr-defined]
        await conn.execute(  # type: ignore[attr-defined]
            "UPDATE entities SET last_accessed = now() WHERE platform = 'gsheets' AND platform_entity_id = $1",
            spreadsheet_id,
        )


async def _fetch_sheet(spreadsheet_id: str) -> EntityBatch:
    import asyncio

    loop = asyncio.get_event_loop()
    sheets_service = await loop.run_in_executor(None, _build_sheets_service)

    spreadsheet: dict[str, Any] = await loop.run_in_executor(
        None,
        lambda: sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute(),
    )

    title: str = spreadsheet.get("properties", {}).get("title", "")
    sheet_names: list[str] = [
        s["properties"]["title"]
        for s in spreadsheet.get("sheets", [])
        if s.get("properties", {}).get("title")
    ]

    # Fetch cell values for all sheets in one batch request
    values_by_range: dict[str, list[list[str]]] = {}
    if sheet_names:
        batch_result: dict[str, Any] = await loop.run_in_executor(
            None,
            lambda: sheets_service.spreadsheets().values().batchGet(
                spreadsheetId=spreadsheet_id,
                ranges=sheet_names,
            ).execute(),
        )
        for vr in batch_result.get("valueRanges", []):
            range_name: str = vr.get("range", "").split("!")[0].strip("'")
            values_by_range[range_name] = vr.get("values", [])

    content = _extract_plain_text(spreadsheet, values_by_range)

    persons: list[PersonRecord] = []
    edges: list[EdgeRecord] = []

    # Fetch owner via Drive API
    try:
        drive_service = await loop.run_in_executor(None, _build_drive_service)
        file_meta: dict[str, Any] = await loop.run_in_executor(
            None,
            lambda: drive_service.files().get(
                fileId=spreadsheet_id,
                fields="owners",
            ).execute(),
        )
        for owner in file_meta.get("owners", []):
            email: str = owner.get("emailAddress", "")
            name: str = owner.get("displayName", "")
            if email:
                persons.append(PersonRecord(
                    platform="gsheets",
                    platform_user_id=email,
                    canonical_email=email,
                    display_name=name or None,
                ))
                edges.append(EdgeRecord(
                    edge_type="authored",
                    source_platform_user_id=email,
                    target_platform_entity_id=spreadsheet_id,
                    platform="gsheets",
                ))
    except Exception:
        logger.debug("Could not fetch Drive ownership for sheet %s", spreadsheet_id)

    entity = EntityRecord(
        entity_type="Spreadsheet",
        platform="gsheets",
        platform_entity_id=spreadsheet_id,
        title=title,
        content=content,
        updated_at=datetime.now(UTC),
    )

    batch = EntityBatch(entities=[entity], persons=persons, edges=edges)
    batch.add_stubs_from(entity)
    return batch
