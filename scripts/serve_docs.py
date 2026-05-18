from __future__ import annotations

import argparse
import importlib
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

build_docs = importlib.import_module("scripts.build_docs")
DOCS_OUT = build_docs.DOCS_OUT
build = build_docs.build


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and serve the AgentGraph docs site.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--skip-build", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.skip_build:
        build()

    directory = str(Path(DOCS_OUT).resolve())
    handler = partial(SimpleHTTPRequestHandler, directory=directory)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving docs at http://{args.host}:{args.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
