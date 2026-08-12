"""Parallel-execution metrics.

Pure functions over measured agent durations, so they can be unit-tested
against the reference numbers without running the workflow.

Worked example from the design spec (seconds):

    planner 1.0, code 2.5, docs 2.0, dependency 2.2, reviewer 1.2

    estimated sequential = 1.0 + 2.5 + 2.0 + 2.2 + 1.2      = 8.9s
    estimated parallel   = 1.0 + max(2.5, 2.0, 2.2) + 1.2   = 4.7s
    estimated saved      = 8.9 - 4.7                        = 4.2s
    estimated speedup    = 8.9 / 4.7                        ≈ 1.89x

Note the wording. "Sequential" is an *estimate* — we never actually run the
workflow serially, we sum the measured concurrent durations. The UI labels it
as an estimate for exactly that reason. Only `duration_ms` is measured directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents import IMPACT_REVIEWER, PARALLEL_AGENTS, PLANNER


@dataclass
class ExecutionMetricsResult:
    duration_ms: int
    estimated_sequential_duration_ms: int
    estimated_parallel_duration_ms: int
    estimated_time_saved_ms: int
    estimated_speedup: float
    parallel_agent_count: int
    total_tokens: int
    estimated_cost: float


def estimate_sequential_ms(durations: dict[str, int]) -> int:
    """What the run would have cost with no concurrency: the sum of all agents."""
    return int(sum(durations.values()))


def estimate_parallel_ms(durations: dict[str, int]) -> int:
    """Theoretical best case: serial stages plus the slowest parallel branch."""
    planner = durations.get(PLANNER, 0)
    reviewer = durations.get(IMPACT_REVIEWER, 0)
    branch_durations = [durations[name] for name in PARALLEL_AGENTS if name in durations]
    slowest_branch = max(branch_durations) if branch_durations else 0
    return int(planner + slowest_branch + reviewer)


def time_saved_ms(sequential_ms: int, actual_ms: int) -> int:
    """Estimated saving. Never negative — concurrency cannot cost you time."""
    return max(0, int(sequential_ms - actual_ms))


def speedup(sequential_ms: int, actual_ms: int) -> float:
    """Estimated speedup factor, rounded to two decimals."""
    if actual_ms <= 0:
        return 1.0
    return round(sequential_ms / actual_ms, 2)


def compute_metrics(
    durations: dict[str, int],
    actual_duration_ms: int,
    total_tokens: int = 0,
    estimated_cost: float = 0.0,
) -> ExecutionMetricsResult:
    """Bundle every metric shown on the execution page."""
    sequential = estimate_sequential_ms(durations)
    parallel = estimate_parallel_ms(durations)

    return ExecutionMetricsResult(
        duration_ms=int(actual_duration_ms),
        estimated_sequential_duration_ms=sequential,
        estimated_parallel_duration_ms=parallel,
        estimated_time_saved_ms=time_saved_ms(sequential, actual_duration_ms),
        estimated_speedup=speedup(sequential, actual_duration_ms),
        parallel_agent_count=len(PARALLEL_AGENTS),
        total_tokens=int(total_tokens),
        estimated_cost=round(float(estimated_cost), 6),
    )
