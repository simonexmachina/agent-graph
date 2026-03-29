"""Google Forms connector."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

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
)
from agentgraph.graph.upsert import upsert_batch

logger = logging.getLogger(__name__)

_STALE_AFTER = 15 * 60


def _build_forms_service() -> Any:
    return build("forms", "v1", credentials=get_provider().get_credentials())


def _build_drive_service() -> Any:
    return build("drive", "v3", credentials=get_provider().get_credentials())


def _render_form_content(form: dict[str, Any]) -> str:
    """Render a Google Form as structured plain text."""
    lines: list[str] = []

    info = form.get("info", {})
    description: str = info.get("description", "")
    if description:
        lines.append(description)
        lines.append("")

    for i, item in enumerate(form.get("items", []), start=1):
        item_title: str = item.get("title", "")
        item_description: str = item.get("description", "")

        if "questionItem" in item:
            question = item["questionItem"].get("question", {})
            required: bool = question.get("required", False)
            req_marker = " *" if required else ""

            lines.append(f"Q{i}: {item_title}{req_marker}")
            if item_description:
                lines.append(f"  {item_description}")

            if "choiceQuestion" in question:
                cq = question["choiceQuestion"]
                q_type: str = cq.get("type", "")
                options: list[str] = [opt.get("value", "") for opt in cq.get("options", [])]
                lines.append(f"  Type: {q_type}")
                if options:
                    lines.append(f"  Options: {', '.join(options)}")
            elif "textQuestion" in question:
                tq = question["textQuestion"]
                paragraph: bool = tq.get("paragraph", False)
                lines.append(f"  Type: {'PARAGRAPH' if paragraph else 'SHORT_ANSWER'}")
            elif "scaleQuestion" in question:
                sq = question["scaleQuestion"]
                low: int = sq.get("low", 1)
                high: int = sq.get("high", 5)
                low_label: str = sq.get("lowLabel", "")
                high_label: str = sq.get("highLabel", "")
                scale_desc = f"  Type: SCALE ({low}–{high})"
                if low_label or high_label:
                    scale_desc += f" [{low_label} → {high_label}]"
                lines.append(scale_desc)
            elif "dateQuestion" in question:
                lines.append("  Type: DATE")
            elif "timeQuestion" in question:
                lines.append("  Type: TIME")
            elif "ratingQuestion" in question:
                lines.append("  Type: RATING")

        elif "questionGroupItem" in item:
            lines.append(f"Q{i}: {item_title} (grid)")
            if item_description:
                lines.append(f"  {item_description}")
            qg = item["questionGroupItem"]
            rows = [r.get("title", "") for r in qg.get("questions", [])]
            cols = [c.get("value", "") for c in qg.get("grid", {}).get("columns", {}).get("options", [])]
            if rows:
                lines.append(f"  Rows: {', '.join(rows)}")
            if cols:
                lines.append(f"  Columns: {', '.join(cols)}")

        elif "pageBreakItem" in item:
            if item_title:
                lines.append(f"\n--- Section: {item_title} ---")
            continue

        lines.append("")

    return "\n".join(lines).strip()


class GoogleFormsConnector(BaseConnector):
    source = "gforms"
    fetch_policy = FetchPolicy(stale_after_seconds=_STALE_AFTER)

    def can_handle(self, url: str) -> bool:
        return "docs.google.com/forms" in url

    async def fetch(self, resource_type: str, resource_id: str, meta: dict[str, str] | None = None) -> EntityBatch:
        last_sync = await self.last_synced_at(resource_id)
        decision = self.fetch_policy.decide(last_sync)

        if decision == FetchPolicy.FRESH:
            logger.debug("gforms/%s is fresh — updating last_accessed only", resource_id)
            await _touch_last_accessed(resource_id)
            return EntityBatch()

        logger.info("Fetching Google Form %s (policy=%s)", resource_id, decision)
        batch = await _fetch_form(resource_id)
        await upsert_batch(batch)
        return batch


async def _touch_last_accessed(form_id: str) -> None:
    from agentgraph.db.connection import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:  # type: ignore[attr-defined]
        await conn.execute(  # type: ignore[attr-defined]
            "UPDATE entities SET last_accessed = now() WHERE platform = 'gforms' AND platform_entity_id = $1",
            form_id,
        )


async def _fetch_form(form_id: str) -> EntityBatch:
    import asyncio

    loop = asyncio.get_event_loop()
    forms_service = await loop.run_in_executor(None, _build_forms_service)

    try:
        form: dict[str, Any] = await loop.run_in_executor(
            None,
            lambda: forms_service.forms().get(formId=form_id).execute(),
        )
    except HttpError as exc:
        if exc.resp.status == 404:
            raise ValueError(f"Google Form not found or not accessible: {form_id}") from exc
        raise

    title: str = form.get("info", {}).get("title", "")
    content = _render_form_content(form)

    persons: list[PersonRecord] = []
    edges: list[EdgeRecord] = []

    try:
        drive_service = await loop.run_in_executor(None, _build_drive_service)
        file_meta: dict[str, Any] = await loop.run_in_executor(
            None,
            lambda: drive_service.files().get(
                fileId=form_id,
                fields="owners",
            ).execute(),
        )
        for owner in file_meta.get("owners", []):
            email: str = owner.get("emailAddress", "")
            name: str = owner.get("displayName", "")
            if email:
                persons.append(PersonRecord(
                    platform="gforms",
                    platform_user_id=email,
                    canonical_email=email,
                    display_name=name or None,
                ))
                edges.append(EdgeRecord(
                    edge_type="authored",
                    source_platform_user_id=email,
                    target_platform_entity_id=form_id,
                    platform="gforms",
                ))
    except Exception:
        logger.debug("Could not fetch Drive ownership for form %s", form_id)

    entity = EntityRecord(
        entity_type="Form",
        platform="gforms",
        platform_entity_id=form_id,
        title=title,
        content=content,
        updated_at=datetime.now(UTC),
    )

    return EntityBatch(
        entities=[entity],
        persons=persons,
        edges=edges,
    )
