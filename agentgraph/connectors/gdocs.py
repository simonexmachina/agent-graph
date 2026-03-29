"""Google Docs connector."""

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
)
from agentgraph.graph.upsert import upsert_batch

logger = logging.getLogger(__name__)

# Staleness: re-fetch if doc hasn't been synced in the last 15 minutes
_STALE_AFTER = 15 * 60


def _build_service() -> Any:
    return build("docs", "v1", credentials=get_provider().get_credentials())


def _build_drive_service() -> Any:
    return build("drive", "v3", credentials=get_provider().get_credentials())


_HEADING_PREFIX: dict[str, str] = {
    "HEADING_1": "# ",
    "HEADING_2": "## ",
    "HEADING_3": "### ",
    "HEADING_4": "#### ",
    "HEADING_5": "##### ",
    "HEADING_6": "###### ",
    "TITLE":     "# ",
    "SUBTITLE":  "## ",
}

# glyphTypes that indicate an ordered list
_ORDERED_GLYPH_TYPES = {"DECIMAL", "ALPHA", "UPPER_ALPHA", "ROMAN", "UPPER_ROMAN"}


def _extract_markdown(doc: dict[str, Any]) -> str:
    """Walk the document body and render content as Markdown."""
    lists: dict[str, Any] = doc.get("lists", {})
    # ordered-list counters: (list_id, nesting_level) → next index
    ordered_counters: dict[tuple[str, int], int] = {}

    lines: list[str] = []
    body = doc.get("body", {})

    for element in body.get("content", []):
        paragraph = element.get("paragraph")
        if not paragraph:
            continue

        style = paragraph.get("paragraphStyle", {})
        named_style = style.get("namedStyleType", "NORMAL_TEXT")
        bullet = paragraph.get("bullet")

        # ── Collect inline text from all text runs ────────────────────────
        inline_parts: list[str] = []
        for pe in paragraph.get("elements", []):
            text_run = pe.get("textRun")
            if not text_run:
                continue
            raw = text_run.get("content", "")
            # Strip the trailing newline that Docs embeds in each paragraph element
            raw = raw.rstrip("\n")
            if not raw:
                continue
            ts = text_run.get("textStyle", {})
            link_url: str = (ts.get("link") or {}).get("url", "")
            bold: bool = ts.get("bold", False)
            italic: bool = ts.get("italic", False)

            text = raw
            if link_url:
                text = f"[{text}]({link_url})"
            if bold:
                text = f"**{text}**"
            if italic:
                text = f"*{text}*"
            inline_parts.append(text)

        inline = "".join(inline_parts).strip()
        if not inline:
            continue

        # ── List items ────────────────────────────────────────────────────
        if bullet:
            list_id: str = bullet.get("listId", "")
            nesting: int = bullet.get("nestingLevel", 0)
            indent = "  " * nesting

            # Determine ordered vs unordered from list properties
            nesting_levels = (
                lists.get(list_id, {})
                    .get("listProperties", {})
                    .get("nestingLevels", [])
            )
            glyph_type = ""
            if nesting < len(nesting_levels):
                glyph_type = nesting_levels[nesting].get("glyphType", "")

            if glyph_type in _ORDERED_GLYPH_TYPES:
                key = (list_id, nesting)
                n = ordered_counters.get(key, 0) + 1
                ordered_counters[key] = n
                lines.append(f"{indent}{n}. {inline}")
            else:
                lines.append(f"{indent}- {inline}")

        # ── Headings ──────────────────────────────────────────────────────
        elif named_style in _HEADING_PREFIX:
            prefix = _HEADING_PREFIX[named_style]
            if lines:
                lines.append("")       # blank line before heading
            lines.append(f"{prefix}{inline}")
            lines.append("")           # blank line after heading

        # ── Normal paragraphs ─────────────────────────────────────────────
        else:
            lines.append(inline)
            lines.append("")           # blank line between paragraphs

    return "\n".join(lines).strip()


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

    async def fetch(self, resource_type: str, resource_id: str, meta: dict[str, str] | None = None) -> EntityBatch:
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
    service = await loop.run_in_executor(None, _build_service)
    doc: dict[str, Any] = await loop.run_in_executor(
        None,
        lambda: service.documents().get(documentId=doc_id).execute(),
    )

    title = doc.get("title", "")
    content = _extract_markdown(doc)
    persons, person_edges = _extract_persons(doc, doc_id)

    # Fetch document owners via Drive API and emit authored edges
    try:
        drive_service = await loop.run_in_executor(None, _build_drive_service)
        file_meta: dict[str, Any] = await loop.run_in_executor(
            None,
            lambda: drive_service.files().get(
                fileId=doc_id,
                fields="owners",
            ).execute(),
        )
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
                person_edges.append(EdgeRecord(
                    edge_type="authored",
                    source_platform_user_id=email,
                    target_platform_entity_id=doc_id,
                    platform="gdocs",
                ))
    except Exception:
        logger.debug("Could not fetch Drive ownership for %s", doc_id)

    entity = EntityRecord(
        entity_type="Document",
        platform="gdocs",
        platform_entity_id=doc_id,
        title=title,
        content=content,
        updated_at=datetime.now(UTC),
    )

    return EntityBatch(
        entities=[entity],
        persons=persons,
        edges=person_edges,
    )
