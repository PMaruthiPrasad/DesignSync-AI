"""The five-agent LangGraph workflow.

                              Planner
                                 |
              +------------------+------------------+
              |                  |                  |
              v                  v                  v
        Code Analyst   Documentation Analyst   Dependency Analyst
              |                  |                  |
              +------------------+------------------+
                                 |
                                 v
                          Impact Reviewer
                                 |
                                 v
                                END

The three middle agents are independent, so they are placed in the same
superstep: LangGraph dispatches them together and awaits them concurrently.
The fan-in edges mean the Impact Reviewer node is not scheduled until all three
have finished — that ordering is enforced by the graph, not by a sleep or by
the UI pretending.

Actual concurrency is bounded by the semaphore in `AgentRuntime`, so a
`concurrency_limit` of 1 genuinely serialises the branches.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents import CODE_ANALYST, DEPENDENCY_ANALYST, DOCS_ANALYST, PLANNER
from app.agents.base import AgentRuntime
from app.agents.code_analyst import run_code_analyst
from app.agents.dependency_analyst import run_dependency_analyst
from app.agents.docs_analyst import run_docs_analyst
from app.agents.impact_reviewer import degraded_report, run_impact_reviewer
from app.agents.planner import fallback_plan, run_planner
from app.agents.prompts import build_base_context
from app.orchestrator.state import WorkflowState
from app.schemas import RepositorySummary

# Agent names as reported to the reviewer when a branch produced no evidence.
EVIDENCE_LABELS = {
    PLANNER: "Planner",
    CODE_ANALYST: "Code Analyst",
    DOCS_ANALYST: "Documentation Analyst",
    DEPENDENCY_ANALYST: "Dependency Analyst",
}


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------


async def planner_node(state: WorkflowState) -> dict[str, Any]:
    record = await run_planner(state["runtime"], state["base_context"], state["summary"])

    if record.succeeded and record.output_data:
        plan = record.output_data
        unavailable: list[str] = []
    else:
        # Degrade rather than abort: continue on deterministic evidence and
        # make sure the reviewer knows the plan was not model-derived.
        plan = fallback_plan(state["base_context"])
        unavailable = [EVIDENCE_LABELS[PLANNER]]

    return {"plan": plan, "agent_records": [record], "unavailable_evidence": unavailable}


async def code_analyst_node(state: WorkflowState) -> dict[str, Any]:
    record = await run_code_analyst(
        state["runtime"], state["base_context"], state["summary"], state["plan"]
    )
    return {
        "code_output": record.output_data if record.succeeded else None,
        "agent_records": [record],
        "unavailable_evidence": [] if record.succeeded else [EVIDENCE_LABELS[CODE_ANALYST]],
    }


async def docs_analyst_node(state: WorkflowState) -> dict[str, Any]:
    record = await run_docs_analyst(
        state["runtime"], state["base_context"], state["summary"], state["plan"]
    )
    return {
        "docs_output": record.output_data if record.succeeded else None,
        "agent_records": [record],
        "unavailable_evidence": [] if record.succeeded else [EVIDENCE_LABELS[DOCS_ANALYST]],
    }


async def dependency_analyst_node(state: WorkflowState) -> dict[str, Any]:
    record = await run_dependency_analyst(
        state["runtime"], state["base_context"], state["summary"], state["plan"]
    )
    return {
        "dependency_output": record.output_data if record.succeeded else None,
        "agent_records": [record],
        "unavailable_evidence": (
            [] if record.succeeded else [EVIDENCE_LABELS[DEPENDENCY_ANALYST]]
        ),
    }


async def impact_reviewer_node(state: WorkflowState) -> dict[str, Any]:
    unavailable = list(state.get("unavailable_evidence", []))

    record = await run_impact_reviewer(
        state["runtime"],
        state["base_context"],
        state["summary"],
        state.get("plan", {}),
        state.get("code_output"),
        state.get("docs_output"),
        state.get("dependency_output"),
        unavailable,
    )

    report = record.output_data if record.succeeded else degraded_report(
        state["base_context"], unavailable
    )
    return {"report": report, "agent_records": [record]}


# --------------------------------------------------------------------------
# Graph
# --------------------------------------------------------------------------


def build_workflow():
    """Compile the workflow graph."""
    builder = StateGraph(WorkflowState)

    builder.add_node(PLANNER, planner_node)
    builder.add_node(CODE_ANALYST, code_analyst_node)
    builder.add_node(DOCS_ANALYST, docs_analyst_node)
    builder.add_node(DEPENDENCY_ANALYST, dependency_analyst_node)
    builder.add_node("impact_reviewer", impact_reviewer_node)

    builder.add_edge(START, PLANNER)

    # Fan-out: one superstep containing three independent branches.
    builder.add_edge(PLANNER, CODE_ANALYST)
    builder.add_edge(PLANNER, DOCS_ANALYST)
    builder.add_edge(PLANNER, DEPENDENCY_ANALYST)

    # Fan-in: the reviewer waits for all three.
    builder.add_edge(CODE_ANALYST, "impact_reviewer")
    builder.add_edge(DOCS_ANALYST, "impact_reviewer")
    builder.add_edge(DEPENDENCY_ANALYST, "impact_reviewer")

    builder.add_edge("impact_reviewer", END)

    return builder.compile()


WORKFLOW = build_workflow()


async def run_workflow(
    runtime: AgentRuntime,
    change_description: str,
    summary: RepositorySummary,
) -> WorkflowState:
    """Run the full workflow and return the final state."""
    base_context = build_base_context(change_description, summary)

    initial: WorkflowState = {
        "runtime": runtime,
        "summary": summary,
        "base_context": base_context,
        "agent_records": [],
        "unavailable_evidence": [],
    }

    return await WORKFLOW.ainvoke(initial)
