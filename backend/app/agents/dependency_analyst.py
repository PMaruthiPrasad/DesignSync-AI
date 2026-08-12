"""Agent 4 — Dependency Analyst.

Interprets the relationships between the changed code and the rest of the
repository. The import graph it reasons over is deterministic AST output, not
model guesswork — the LLM's job here is interpretation, not discovery.

Runs concurrently with the Code and Documentation analysts.
"""

from __future__ import annotations

from app.agents import DEPENDENCY_ANALYST
from app.agents.base import AgentRecord, AgentRuntime, run_agent
from app.agents.outputs import DependencyAnalystOutput
from app.agents.prompts import DEPENDENCY_ANALYST_SYSTEM, dependency_analyst_prompt
from app.schemas import RepositorySummary


async def run_dependency_analyst(
    runtime: AgentRuntime, base_context: dict, summary: RepositorySummary, plan: dict
) -> AgentRecord:
    return await run_agent(
        runtime,
        agent_name=DEPENDENCY_ANALYST,
        system_prompt=DEPENDENCY_ANALYST_SYSTEM,
        user_prompt=dependency_analyst_prompt(base_context, summary, plan),
        response_schema=DependencyAnalystOutput,
        input_summary={
            "primary_target": base_context.get("primary_target"),
            "direct_importers": summary.imported_by.get(base_context.get("primary_target", ""), []),
        },
    )
