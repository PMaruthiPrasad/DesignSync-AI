"""Orchestration: ordering, real concurrency, and the fan-in barrier.

The claim "the three analysis agents run concurrently" is the core engineering
claim of this project, so it is tested against measured wall-clock timings and
overlapping intervals — not against the shape of the graph definition.
"""

import asyncio
import time

import pytest

from app.agents import CODE_ANALYST, DEPENDENCY_ANALYST, DOCS_ANALYST, IMPACT_REVIEWER, PLANNER
from app.agents.base import AgentRuntime
from app.llm.mock_provider import MockLLMProvider
from app.orchestrator.graph import run_workflow

from tests.conftest import DEMO_CHANGE

LATENCY_SCALE = 0.1


def records_by_name(state) -> dict:
    return {r.agent_name: r for r in state["agent_records"]}


async def execute(demo_summary, concurrency_limit=3):
    runtime = AgentRuntime.create(
        MockLLMProvider(latency_scale=LATENCY_SCALE), concurrency_limit=concurrency_limit
    )
    started = time.perf_counter()
    state = await run_workflow(runtime, DEMO_CHANGE, demo_summary)
    return state, (time.perf_counter() - started) * 1000


async def test_workflow_completes_successfully(demo_summary):
    state, _ = await execute(demo_summary)
    records = records_by_name(state)

    assert set(records) == {
        PLANNER,
        CODE_ANALYST,
        DOCS_ANALYST,
        DEPENDENCY_ANALYST,
        IMPACT_REVIEWER,
    }
    assert all(record.succeeded for record in records.values())
    assert state["report"]["overall_severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")


async def test_planner_executes_before_the_analysts(demo_summary):
    state, _ = await execute(demo_summary)
    records = records_by_name(state)

    planner_end = records[PLANNER].completed_at
    for name in (CODE_ANALYST, DOCS_ANALYST, DEPENDENCY_ANALYST):
        assert records[name].started_at >= planner_end, f"{name} started before the planner finished"


async def test_three_analysts_actually_overlap_in_wall_clock(demo_summary):
    """Their execution intervals must genuinely intersect."""
    state, _ = await execute(demo_summary, concurrency_limit=3)
    records = records_by_name(state)

    intervals = [
        (records[name].started_at, records[name].completed_at)
        for name in (CODE_ANALYST, DOCS_ANALYST, DEPENDENCY_ANALYST)
    ]

    # Every pair of branches must overlap: max(starts) < min(ends).
    latest_start = max(start for start, _ in intervals)
    earliest_end = min(end for _, end in intervals)
    assert latest_start < earliest_end, (
        "analysis agents did not overlap; they ran sequentially"
    )


async def test_parallel_run_is_faster_than_the_sum_of_its_agents(demo_summary):
    state, wall_ms = await execute(demo_summary, concurrency_limit=3)
    total_agent_ms = sum(r.duration_ms for r in state["agent_records"])

    assert wall_ms < total_agent_ms, "wall clock should beat the sequential sum"
    # The three branches take ~6.7 units of the ~8.9 total; expect a real win.
    assert total_agent_ms / wall_ms > 1.3


async def test_reviewer_waits_for_every_analyst(demo_summary):
    """The fan-in barrier: synthesis cannot begin on partial evidence."""
    state, _ = await execute(demo_summary)
    records = records_by_name(state)

    reviewer_start = records[IMPACT_REVIEWER].started_at
    for name in (CODE_ANALYST, DOCS_ANALYST, DEPENDENCY_ANALYST):
        assert records[name].completed_at <= reviewer_start, (
            f"reviewer started before {name} finished"
        )


async def test_concurrency_limit_of_one_serialises_the_branches(demo_summary):
    """The concurrency limit is a real bound, not a display setting."""
    state, _ = await execute(demo_summary, concurrency_limit=1)
    records = records_by_name(state)

    intervals = sorted(
        (
            (records[name].started_at, records[name].completed_at)
            for name in (CODE_ANALYST, DOCS_ANALYST, DEPENDENCY_ANALYST)
        ),
        key=lambda pair: pair[0],
    )

    for (_, first_end), (second_start, _) in zip(intervals, intervals[1:]):
        assert second_start >= first_end, "branches overlapped despite a limit of 1"


async def test_serialised_run_is_slower_than_the_parallel_run(demo_summary):
    _, parallel_ms = await execute(demo_summary, concurrency_limit=3)
    _, serial_ms = await execute(demo_summary, concurrency_limit=1)

    assert serial_ms > parallel_ms


async def test_semaphore_caps_simultaneous_provider_calls(demo_summary):
    """Directly observe that no more than `limit` calls are ever in flight."""
    in_flight = 0
    peak = 0
    lock = asyncio.Lock()

    class CountingProvider(MockLLMProvider):
        async def complete(self, **kwargs):
            nonlocal in_flight, peak
            async with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            try:
                return await super().complete(**kwargs)
            finally:
                async with lock:
                    in_flight -= 1

    runtime = AgentRuntime.create(
        CountingProvider(latency_scale=LATENCY_SCALE), concurrency_limit=2
    )
    await run_workflow(runtime, DEMO_CHANGE, demo_summary)

    assert peak <= 2, f"{peak} concurrent calls exceeded the limit of 2"
    assert peak == 2, "the limit should actually be reached with three ready branches"


async def test_every_agent_reports_observability_data(demo_summary):
    state, _ = await execute(demo_summary)

    for record in state["agent_records"]:
        assert record.duration_ms >= 0
        assert record.total_tokens > 0
        assert record.estimated_cost > 0
        assert record.model and record.provider
        assert record.system_prompt and record.user_prompt
        assert record.confidence is not None


@pytest.mark.parametrize("limit", [1, 2, 3, 5])
async def test_report_is_identical_regardless_of_concurrency(demo_summary, limit):
    """Concurrency is an execution detail; it must not change the findings."""
    state, _ = await execute(demo_summary, concurrency_limit=limit)
    assert state["report"]["overall_severity"] == "HIGH"
    assert [c["component"] for c in state["report"]["affected_components"]][0] == (
        "pricing/discount.py"
    )
