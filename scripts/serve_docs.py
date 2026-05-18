from __future__ import annotations

import argparse
import importlib
import sys
import threading
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
    parser.add_argument(
        "--watch",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Rebuild when docs source files change (default: enabled).",
    )
    parser.add_argument(
        "--watch-interval",
        type=float,
        default=0.5,
        help="Polling interval in seconds for watch mode.",
    )
    return parser.parse_args()


def watch_paths() -> tuple[Path, ...]:
    return (
        Path("docs-src"),
        Path("scripts/build_docs.py"),
        Path("scripts/serve_docs.py"),
    )


def snapshot_mtimes(paths: tuple[Path, ...]) -> dict[Path, float]:
    mtimes: dict[Path, float] = {}
    for path in paths:
        if path.is_dir():
            for child in path.rglob("*"):
                if child.is_file():
                    mtimes[child] = child.stat().st_mtime
        elif path.is_file():
            mtimes[path] = path.stat().st_mtime
    return mtimes


def watch_and_rebuild(stop_event: threading.Event, interval: float) -> None:
    paths = watch_paths()
    previous = snapshot_mtimes(paths)
    while not stop_event.wait(interval):
        current = snapshot_mtimes(paths)
        if current == previous:
            continue
        previous = current
        try:
            build()
            print("Rebuilt docs.")
        except Exception as exc:
            print(f"Docs rebuild failed: {exc}", file=sys.stderr)


def main() -> None:
    args = parse_args()
    if not args.skip_build:
        build()

    directory = str(Path(DOCS_OUT).resolve())
    handler = partial(SimpleHTTPRequestHandler, directory=directory)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    stop_event = threading.Event()
    watcher: threading.Thread | None = None
    if args.watch:
        watcher = threading.Thread(
            target=watch_and_rebuild,
            args=(stop_event, args.watch_interval),
            daemon=True,
        )
        watcher.start()
    print(f"Serving docs at http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    finally:
        stop_event.set()
        server.server_close()
        if watcher is not None:
            watcher.join(timeout=max(args.watch_interval * 2, 1.0))


if __name__ == "__main__":
    main()
