"""Preview expiration without changing the AgentGraph database."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentgraph.config import get_settings
from agentgraph.core.runtime import backend_context
from agentgraph.graph.expiration import parse_retention_window, run_expiration
from agentgraph.logging import configure_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview AgentGraph expiration without changing the database."
    )
    parser.add_argument(
        "--retention",
        required=True,
        help="Duration (30m, 12h, 30d, 2w), ISO timestamp, or viewer date (DD/MM/YYYY, HH:MM:SS).",
    )
    return parser.parse_args()


async def main(retention: str) -> int:
    retention_days = parse_retention_window(retention)
    settings = get_settings()
    configure_logging(settings.log_level)
    async with backend_context():
        return await run_expiration(retention_days=retention_days, dry_run=True)


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(main(args.retention))
    except ValueError as exc:
        raise SystemExit(f"error: {exc}") from exc
