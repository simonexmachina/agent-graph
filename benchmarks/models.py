"""Data contracts for reproducible benchmark runs."""

from __future__ import annotations

import platform
from datetime import UTC, datetime
from math import ceil
from statistics import median
from typing import Literal

from pydantic import BaseModel, Field


class CorpusSpec(BaseModel):
    """A deterministic corpus shape used by benchmark scenarios."""

    name: str
    entity_count: int = Field(ge=1)
    cluster_count: int = Field(default=20, ge=1)
    high_degree_edges: int = Field(default=0, ge=0)
    batch_size: int = Field(default=500, ge=1)
    embedding_dimensions: int = Field(default=384, ge=8)


class SampleSummary(BaseModel):
    """Latency distribution in milliseconds for one workload."""

    count: int = Field(ge=1)
    min_ms: float = Field(ge=0)
    p50_ms: float = Field(ge=0)
    p95_ms: float = Field(ge=0)
    p99_ms: float = Field(ge=0)
    max_ms: float = Field(ge=0)


class QualityResult(BaseModel):
    """Retrieval quality outcome for a single query workload."""

    expected_ids: list[str]
    must_return_ids: list[str] = []
    returned_ids: list[str]
    recall_at_limit: float = Field(ge=0, le=1)
    must_return_ids_present: bool


class WorkloadResult(BaseModel):
    """A measured scenario and any corresponding retrieval assertion."""

    name: str
    kind: Literal["backend", "api", "frontend"]
    warmup_iterations: int = Field(ge=0)
    summary: SampleSummary
    operations_per_second: float = Field(ge=0)
    phase_summaries: dict[str, SampleSummary] = Field(default_factory=dict)
    quality: QualityResult | None = None


class BenchmarkRun(BaseModel):
    """Portable JSON report produced by the benchmark runner."""

    schema_version: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    git_sha: str | None = None
    python_version: str = Field(default_factory=platform.python_version)
    platform: str = Field(default_factory=platform.platform)
    corpus: CorpusSpec
    vector_mode: str
    cold: bool
    workloads: list[WorkloadResult]


def summarize_samples(samples_ms: list[float]) -> SampleSummary:
    """Summarize recorded latencies using nearest-rank percentiles."""
    if not samples_ms:
        raise ValueError("At least one latency sample is required")
    ordered = sorted(samples_ms)

    def percentile(percent: float) -> float:
        index = max(0, min(len(ordered) - 1, ceil(len(ordered) * percent) - 1))
        return ordered[index]

    return SampleSummary(
        count=len(ordered),
        min_ms=ordered[0],
        p50_ms=float(median(ordered)),
        p95_ms=percentile(0.95),
        p99_ms=percentile(0.99),
        max_ms=ordered[-1],
    )
