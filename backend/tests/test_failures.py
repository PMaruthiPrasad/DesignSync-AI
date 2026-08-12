"""Failure handling.

The rule: an agent failure is contained, recorded, and reported downstream —
never silently swallowed, and never allowed to present a partial picture as a
complete one.
"""

from pydantic import BaseModel

from app.agents import CODE_ANALYST, DOCS_ANALYST, IMPACT_REVIEWER, PLANNER
from app.agents.base import AgentRuntime
from app.llm.base import LLMError, LLMResponse
from app.llm.mock_provider import MockLLMProvider
from app.orchestrator.graph import run_workflow

from tests.conftest import DEMO_CHANGE

LATENCY_SCALE = 0.05


class FailingProvider(MockLLMProvider):
    """Mock provider that fails for specific agents."""

    def __init__(self, failing_agents: set[str], **kwargs):
        super().__init__(**kwargs)
        self.failing_agents = failing_agents

    async def complete(self, *, agent_name: str, **kwargs):
        if agent_name in self.failing_agents:
            raise LLMError(f"simulated upstream failure for {agent_name}")
        return await super().complete(agent_name=agent_name, **kwargs)


class MalformedProvider(MockLLMProvider):
    """Returns JSON that does not satisfy the agent's schema."""

    def __init__(self, broken_agents: set[str], **kwargs):
        super().__init__(**kwargs)
        self.broken_agents = broken_agents

    async def complete(
        self, *, system_prompt: str, user_prompt: str, response_schema: type[BaseModel], agent_name: str
    ):
        if agent_name in self.broken_agents:
            return LLMResponse(
                content='{"totally": "wrong shape"}',
                model="mock-designsync-1",
                provider="mock",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                estimated_cost=0.0001,
            )
        return await super().complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=response_schema,
            agent_name=agent_name,
        )


async def run_with(provider, demo_summary, concurrency_limit=3):
    runtime = AgentRuntime.create(provider, concurrency_limit=concurrency_limit)
    return await run_workflow(runtime, DEMO_CHANGE, demo_summary)


def records_by_name(state) -> dict:
    return {r.agent_name: r for r in state["agent_records"]}


async def test_code_analyst_failure_is_marked_failed(demo_summary):
    state = await run_with(
        FailingProvider({CODE_ANALYST}, latency_scale=LATENCY_SCALE), demo_summary
    )
    record = records_by_name(state)[CODE_ANALYST]

    assert record.status == "FAILED"
    assert record.output_data is None


async def test_code_analyst_failure_preserves_the_error(demo_summary):
    state = await run_with(
        FailingProvider({CODE_ANALYST}, latency_scale=LATENCY_SCALE), demo_summary
    )
    record = records_by_name(state)[CODE_ANALYST]

    assert record.error
    assert "simulated upstream failure" in record.error


async def test_workflow_continues_after_one_branch_fails(demo_summary):
    state = await run_with(
        FailingProvider({CODE_ANALYST}, latency_scale=LATENCY_SCALE), demo_summary
    )
    records = records_by_name(state)

    assert records[DOCS_ANALYST].succeeded
    assert records[IMPACT_REVIEWER].succeeded
    assert state["report"] is not None


async def test_reviewer_is_told_which_evidence_is_missing(demo_summary):
    """The reviewer must know the Code Analyst produced nothing."""
    state = await run_with(
        FailingProvider({CODE_ANALYST}, latency_scale=LATENCY_SCALE), demo_summary
    )

    assert "Code Analyst" in state["unavailable_evidence"]

    reviewer_prompt = records_by_name(state)[IMPACT_REVIEWER].user_prompt
    assert "Code Analyst" in reviewer_prompt
    assert "failed" in reviewer_prompt.lower()


async def test_report_flags_the_gap_rather_than_hiding_it(demo_summary):
    state = await run_with(
        FailingProvider({CODE_ANALYST}, latency_scale=LATENCY_SCALE), demo_summary
    )
    report = state["report"]

    combined = " ".join(report["uncertain_findings"] + report["contradictions"]).lower()
    assert "code analyst" in combined
    assert report["confidence"] < 0.9, "confidence must drop when evidence is missing"


async def test_planner_failure_falls_back_to_deterministic_plan(demo_summary):
    """The workflow degrades to AST evidence rather than collapsing."""
    state = await run_with(FailingProvider({PLANNER}, latency_scale=LATENCY_SCALE), demo_summary)
    records = records_by_name(state)

    assert records[PLANNER].status == "FAILED"
    assert state["plan"]["degraded"] is True
    assert "pricing/discount.py" in state["plan"]["investigation_targets"]
    assert records[IMPACT_REVIEWER].succeeded


async def test_all_analysts_failing_still_produces_a_report(demo_summary):
    state = await run_with(
        FailingProvider({CODE_ANALYST, DOCS_ANALYST, "dependency_analyst"}, latency_scale=LATENCY_SCALE),
        demo_summary,
    )

    assert state["report"] is not None
    assert len(state["unavailable_evidence"]) == 3
    assert state["report"]["confidence"] < 0.7


async def test_malformed_response_is_caught_not_half_parsed(demo_summary):
    """Schema-invalid JSON must fail the agent, not corrupt the report."""
    state = await run_with(
        MalformedProvider({CODE_ANALYST}, latency_scale=LATENCY_SCALE), demo_summary
    )
    record = records_by_name(state)[CODE_ANALYST]

    assert record.status == "FAILED"
    assert "ValidationError" in record.error or "validation" in record.error.lower()
    assert state["report"] is not None


async def test_reviewer_failure_still_returns_a_degraded_report(demo_summary):
    state = await run_with(
        FailingProvider({IMPACT_REVIEWER}, latency_scale=LATENCY_SCALE), demo_summary
    )

    assert records_by_name(state)[IMPACT_REVIEWER].status == "FAILED"
    assert state["report"]["degraded"] is True
    assert state["report"]["confidence"] <= 0.3


async def test_failed_agent_still_records_timing(demo_summary):
    """Observability must survive failure — you need the data to debug it."""
    state = await run_with(
        FailingProvider({CODE_ANALYST}, latency_scale=LATENCY_SCALE), demo_summary
    )
    record = records_by_name(state)[CODE_ANALYST]

    assert record.started_at is not None
    assert record.completed_at is not None
    assert record.duration_ms >= 0
