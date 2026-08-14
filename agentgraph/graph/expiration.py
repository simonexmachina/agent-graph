"""Expiration of observed, owned, and graph-connected entities."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from agentgraph.config import get_settings
from agentgraph.core.context import get_backend

logger = logging.getLogger(__name__)

_RETENTION_PATTERN = re.compile(r"^(?P<value>[0-9]+(?:\.[0-9]+)?)(?P<unit>[mhdw])$")
_RETENTION_UNIT_DAYS = {"m": 1 / (24 * 60), "h": 1 / 24, "d": 1.0, "w": 7.0}
_VIEWER_TIMESTAMP_FORMAT = "%d/%m/%Y, %H:%M:%S"


def parse_retention_window(value: str, now: datetime | None = None) -> float:
    """Convert a duration or ISO-8601 timestamp to fractional days."""
    match = _RETENTION_PATTERN.fullmatch(value.strip().lower())
    if match is not None:
        amount = float(match.group("value"))
        if amount <= 0:
            raise ValueError("retention must be greater than zero")
        return amount * _RETENTION_UNIT_DAYS[match.group("unit")]

    timestamp_value = value.strip()
    try:
        timestamp = datetime.fromisoformat(timestamp_value.replace("Z", "+00:00"))
    except ValueError:
        try:
            timestamp = datetime.strptime(timestamp_value, _VIEWER_TIMESTAMP_FORMAT)
        except ValueError as exc:
            raise ValueError(
                "retention must be a duration such as 30m, an ISO-8601 timestamp, "
                "or a viewer date like '14/08/2026, 09:51:54'"
            ) from exc
    current_time = now or datetime.now().astimezone()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=current_time.tzinfo)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    elapsed_days = (current_time - timestamp).total_seconds() / 86_400
    if elapsed_days <= 0:
        raise ValueError(
            "retention timestamp must be in the past"
        )
    return elapsed_days


async def run_expiration(retention_days: float | None = None, dry_run: bool = False) -> int:
    """
    Collect expired entities, optionally rolling back instead of committing.

    Returns the total number of rows deleted, or the number that would be
    deleted when ``dry_run`` is true.
    """
    settings = get_settings()
    selected_retention_days = (
        float(settings.retention_days) if retention_days is None else retention_days
    )
    action = "would remove" if dry_run else "removed"
    mode = "dry-run " if dry_run else ""
    logger.info(
        "Starting %sexpiration with retention window %.6g days",
        mode,
        selected_retention_days,
    )
    total = await get_backend().expire_entities(selected_retention_days, dry_run=dry_run)
    logger.info(
        "Expiration complete: %s %d entities (retention=%.6g days, dry_run=%s)",
        action,
        total,
        selected_retention_days,
        dry_run,
    )
    if dry_run:
        logger.info("Dry-run complete: no changes were committed")
    return total
