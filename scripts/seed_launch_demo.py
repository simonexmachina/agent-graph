"""Compatibility wrapper for the packaged Atlas demo adder."""

from __future__ import annotations

import asyncio
import json
from argparse import ArgumentParser

from agentgraph.config import get_config_paths
from agentgraph.demo import add_demo


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    args = parser.parse_args()
    result = asyncio.run(add_demo(get_config_paths()[0]))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
