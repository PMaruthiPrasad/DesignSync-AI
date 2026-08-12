"""Agent 2 — Code Analyst.

Analyses the code affected by the change: functions, classes, imports, callers,
references and downstream modules, separating DIRECT impact from
POTENTIAL_DOWNSTREAM impact.

Runs concurrently with the Documentation and Dependency analysts.
"""

from __future__ import annotations

from app.agents import CODE_ANALYST
from app.agents.base import AgentRecord, AgentRuntime, run_agent
from app.agents.outputs import CodeAnalystOutput
from app.agents.prompts import CODE_ANALYST_SYSTEM, code_analyst_prompt
from app.schemas import RepositorySummary


async def run_code_analyst(
    runtime: AgentRuntime, base_context: dict, summary: RepositorySummary, plan: dict
) -> AgentRecord:
    return await run_agent(
        runtime,
        agent_name=CODE_ANALYST,
        system_prompt=CODE_ANALYST_SYSTEM,
        user_prompt=code_analyst_prompt(base_context, summary, plan),
        response_schema=CodeAnalystOutput,
        input_summary={
            "investigation_targets": plan.get("investigation_targets", []),
            "primary_target": base_context.get("primary_target"),
            "downstream_files": base_context.get("downstream_files", []),
        },
    )
