"""Agent 1 — Planner.

Converts a change description into an investigation plan. It scopes the work
and hands targets to the specialists; it deliberately does not analyse.

If the Planner fails, the workflow does not stop: a deterministic fallback plan
is built from the AST-derived candidates so the specialists still have targets.
The failure is recorded and reported to the Impact Reviewer.
"""

from __future__ import annotations

from app.agents import PLANNER
from app.agents.base import AgentRecord, AgentRuntime, run_agent
from app.agents.outputs import PlannerOutput
from app.agents.prompts import PLANNER_SYSTEM, planner_prompt
from app.schemas import RepositorySummary


async def run_planner(
    runtime: AgentRuntime, base_context: dict, summary: RepositorySummary
) -> AgentRecord:
    return await run_agent(
        runtime,
        agent_name=PLANNER,
        system_prompt=PLANNER_SYSTEM,
        user_prompt=planner_prompt(base_context, summary),
        response_schema=PlannerOutput,
        input_summary={
            "change_description": base_context["change_description"],
            "repository": base_context["repository_name"],
            "candidate_files": [c["file"] for c in base_context["candidate_files"]],
        },
    )


def fallback_plan(base_context: dict) -> dict:
    """Deterministic plan used when the Planner agent fails.

    Built entirely from AST evidence, so the workflow can continue safely
    instead of collapsing on a single agent failure.
    """
    targets = [c["file"] for c in base_context.get("candidate_files", [])][:6]
    return {
        "change_summary": base_context.get("change_description", "")[:400],
        "primary_area": base_context.get("primary_area", "unknown"),
        "investigation_targets": targets,
        "reasoning": (
            "Planner agent failed. This plan was derived deterministically from "
            "repository structure and keyword targeting, without model reasoning."
        ),
        "confidence": 0.4,
        "degraded": True,
    }
