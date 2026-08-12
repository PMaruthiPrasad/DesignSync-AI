"""Agent 3 — Documentation Analyst.

Finds documentation that the change has made stale: READMEs, docs/*.md, API
references, usage examples and configuration docs.

Runs concurrently with the Code and Dependency analysts.
"""

from __future__ import annotations

from app.agents import DOCS_ANALYST
from app.agents.base import AgentRecord, AgentRuntime, run_agent
from app.agents.outputs import DocsAnalystOutput
from app.agents.prompts import DOCS_ANALYST_SYSTEM, docs_analyst_prompt
from app.schemas import RepositorySummary


async def run_docs_analyst(
    runtime: AgentRuntime, base_context: dict, summary: RepositorySummary, plan: dict
) -> AgentRecord:
    return await run_agent(
        runtime,
        agent_name=DOCS_ANALYST,
        system_prompt=DOCS_ANALYST_SYSTEM,
        user_prompt=docs_analyst_prompt(base_context, summary, plan),
        response_schema=DocsAnalystOutput,
        input_summary={
            "documentation_files": summary.documentation_files,
            "change_description": base_context.get("change_description"),
        },
    )
