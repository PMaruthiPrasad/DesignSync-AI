"""Parallel-execution metric calculations.

The headline case is the worked example from the design spec.
"""

from app.services.metrics import (
    compute_metrics,
    estimate_parallel_ms,
    estimate_sequential_ms,
    speedup,
    time_saved_ms,
)

# planner 1.0s, code 2.5s, docs 2.0s, dependency 2.2s, reviewer 1.2s
SPEC_DURATIONS = {
    "planner": 1000,
    "code_analyst": 2500,
    "documentation_analyst": 2000,
    "dependency_analyst": 2200,
    "impact_reviewer": 1200,
}


def test_spec_example_sequential_estimate():
    assert estimate_sequential_ms(SPEC_DURATIONS) == 8900


def test_spec_example_parallel_estimate():
    # planner + slowest branch + reviewer = 1.0 + 2.5 + 1.2
    assert estimate_parallel_ms(SPEC_DURATIONS) == 4700


def test_spec_example_time_saved():
    assert time_saved_ms(8900, 4700) == 4200


def test_spec_example_speedup():
    assert speedup(8900, 4700) == 1.89


def test_compute_metrics_bundles_the_spec_example():
    result = compute_metrics(SPEC_DURATIONS, actual_duration_ms=4700, total_tokens=1234, estimated_cost=0.5)

    assert result.estimated_sequential_duration_ms == 8900
    assert result.estimated_parallel_duration_ms == 4700
    assert result.estimated_time_saved_ms == 4200
    assert result.estimated_speedup == 1.89
    assert result.parallel_agent_count == 3
    assert result.total_tokens == 1234


def test_time_saved_is_never_negative():
    """Overhead can make a run slower than the estimate; it cannot 'cost' time."""
    assert time_saved_ms(1000, 1500) == 0


def test_speedup_handles_zero_duration():
    assert speedup(1000, 0) == 1.0


def test_parallel_estimate_ignores_missing_branches():
    durations = {"planner": 500, "impact_reviewer": 500}
    assert estimate_parallel_ms(durations) == 1000


def test_sequential_estimate_of_empty_run_is_zero():
    assert estimate_sequential_ms({}) == 0
