"""Combined backend and HTTP benchmark entry point."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from benchmarks.api import run_api_suite
from benchmarks.models import BenchmarkRun, CorpusSpec
from benchmarks.runner import run_backend_suite, write_report


async def run_suite(
    database_directory: Path,
    spec: CorpusSpec,
    *,
    iterations: int,
    include_api: bool,
    vector_mode: str,
) -> BenchmarkRun:
    """Run all requested server-side workload layers with one corpus specification."""
    backend_report = await run_backend_suite(
        database_directory / "backend.db", spec, iterations=iterations, vector_mode=vector_mode
    )
    workloads = list(backend_report.workloads)
    if include_api:
        api_report = await run_api_suite(
            database_directory / "api.db", spec, iterations=iterations, vector_mode=vector_mode
        )
        workloads.extend(api_report.workloads)
    return backend_report.model_copy(update={"workloads": workloads})


def main() -> None:
    """Run server-side workloads via ``python -m benchmarks.suite``."""
    parser = argparse.ArgumentParser(description="Run the AgentGraph performance suite")
    parser.add_argument("--directory", type=Path, default=Path(".benchmarks/latest"))
    parser.add_argument("--output", type=Path, default=Path(".benchmarks/latest.json"))
    parser.add_argument("--entities", type=int, default=10_000)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--without-api", action="store_true")
    parser.add_argument(
        "--vector-mode", choices=("sqlite-vec", "numpy", "bm25-only"), default="sqlite-vec"
    )
    args = parser.parse_args()
    report = asyncio.run(
        run_suite(
            args.directory,
            CorpusSpec(
                name=f"generated-{args.entities}",
                entity_count=args.entities,
                high_degree_edges=min(args.entities - 1, 250),
            ),
            iterations=args.iterations,
            include_api=not args.without_api,
            vector_mode=args.vector_mode,
        )
    )
    write_report(report, args.output)


if __name__ == "__main__":
    main()
