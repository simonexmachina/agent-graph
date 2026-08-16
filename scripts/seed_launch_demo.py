"""Compatibility wrapper for the packaged Atlas demo seeder."""

from __future__ import annotations

import asyncio
import json
from argparse import ArgumentParser, Namespace
from pathlib import Path

from agentgraph.demo import seed_demo


def parse_args() -> Namespace:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", required=True, type=Path)
    parser.add_argument("--reset", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = asyncio.run(seed_demo(args.config_dir, reset=args.reset))
    except (FileExistsError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
