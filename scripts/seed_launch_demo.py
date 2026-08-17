"""Compatibility wrapper for the packaged Atlas demo seeder."""

from __future__ import annotations

import asyncio
import json
from argparse import ArgumentParser

from agentgraph.config import get_config_paths
from agentgraph.demo import seed_demo


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    try:
        result = asyncio.run(seed_demo(get_config_paths()[0], reset=args.reset))
    except (FileExistsError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
