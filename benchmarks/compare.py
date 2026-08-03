"""Scenario-aware comparison of benchmark reports."""

from __future__ import annotations

from pydantic import BaseModel

from benchmarks.models import BenchmarkRun


class Regression(BaseModel):
    """A material result degradation relative to a compatible baseline."""

    workload: str
    metric: str
    baseline: float | bool
    current: float | bool
    message: str


def compare_runs(
    baseline: BenchmarkRun,
    current: BenchmarkRun,
    *,
    allowed_latency_regression: float = 0.15,
    allowed_recall_regression: float = 0.0,
) -> list[Regression]:
    """Find p95 and quality regressions without hiding scenario-level outcomes."""
    if baseline.corpus != current.corpus or baseline.vector_mode != current.vector_mode:
        raise ValueError("Benchmark reports must use the same corpus and vector mode")
    baseline_by_name = {workload.name: workload for workload in baseline.workloads}
    regressions: list[Regression] = []
    for workload in current.workloads:
        previous = baseline_by_name.get(workload.name)
        if previous is None:
            continue
        previous_p95 = previous.summary.p95_ms
        current_p95 = workload.summary.p95_ms
        if previous_p95 and current_p95 > previous_p95 * (1 + allowed_latency_regression):
            regressions.append(
                Regression(
                    workload=workload.name,
                    metric="p95_ms",
                    baseline=previous_p95,
                    current=current_p95,
                    message=(
                        f"p95 rose from {previous_p95:.2f}ms to {current_p95:.2f}ms "
                        f"(budget: {allowed_latency_regression:.0%})"
                    ),
                )
            )
        if previous.quality is None or workload.quality is None:
            continue
        if (
            workload.quality.recall_at_limit
            < previous.quality.recall_at_limit - allowed_recall_regression
        ):
            regressions.append(
                Regression(
                    workload=workload.name,
                    metric="recall_at_limit",
                    baseline=previous.quality.recall_at_limit,
                    current=workload.quality.recall_at_limit,
                    message="retrieval recall regressed",
                )
            )
        if (
            workload.quality.ndcg_at_limit
            < previous.quality.ndcg_at_limit - allowed_recall_regression
        ):
            regressions.append(
                Regression(
                    workload=workload.name,
                    metric="ndcg_at_limit",
                    baseline=previous.quality.ndcg_at_limit,
                    current=workload.quality.ndcg_at_limit,
                    message="retrieval ranking quality regressed",
                )
            )
        if not workload.quality.must_return_ids_present:
            regressions.append(
                Regression(
                    workload=workload.name,
                    metric="must_return_ids_present",
                    baseline=previous.quality.must_return_ids_present,
                    current=False,
                    message="a required retrieval result is absent",
                )
            )
    return regressions
