"""Tests for deterministic benchmark fixtures and report contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.corpus import build_seeded_corpus
from benchmarks.models import CorpusSpec, summarize_samples
from benchmarks.runner import run_backend_suite, write_report


def test_corpus_is_deterministic_and_contains_a_high_degree_hub() -> None:
    spec = CorpusSpec(
        name="tiny", entity_count=20, cluster_count=4, high_degree_edges=8, batch_size=10
    )
    first_batches, first = build_seeded_corpus(spec)
    second_batches, second = build_seeded_corpus(spec)

    assert first == second
    assert first_batches == second_batches
    assert sum(len(batch.entities) for batch in first_batches) == 20
    assert sum(len(batch.edges) for batch in first_batches) >= 8


def test_latency_summary_uses_nearest_rank_percentiles() -> None:
    summary = summarize_samples([1.0, 2.0, 3.0, 4.0, 5.0])

    assert summary.p50_ms == 3.0
    assert summary.p95_ms == 5.0
    assert summary.p99_ms == 5.0


@pytest.mark.integration
async def test_backend_suite_writes_quality_checked_report(tmp_path: Path) -> None:
    spec = CorpusSpec(
        name="tiny", entity_count=30, cluster_count=5, high_degree_edges=10, batch_size=10
    )
    report = await run_backend_suite(
        tmp_path / "benchmark.db", spec, iterations=2, warmup_iterations=0
    )
    output = tmp_path / "report.json"
    write_report(report, output)

    assert {workload.name for workload in report.workloads} == {
        "search.exact",
        "search.semantic_sparse",
        "search.common_term",
        "retrieval.filtered_documents",
        "graph.high_degree_traversal",
    }
    exact = next(workload for workload in report.workloads if workload.name == "search.exact")
    assert exact.quality is not None
    assert exact.quality.required_ids_present
    assert '"schema_version": 1' in output.read_text()
