"""Agent 5 — Impact Reviewer.

The synthesis and quality-control stage. It waits for all three analysis
branches, consolidates their findings, flags contradictions and unsupported
claims, and sorts everything into confirmed / likely / uncertain tiers.

It is explicitly told which upstream agents failed, so a partial picture is
reported as partial rather than presented as complete.
"""

from __future__ import annotations

from app.agents import IMPACT_REVIEWER
from app.agents.base import AgentRecord, AgentRuntime, run_agent
from app.agents.outputs import ImpactReviewerOutput
from app.agents.prompts import IMPACT_REVIEWER_SYSTEM, impact_reviewer_prompt
from app.schemas import RepositorySummary


async def run_impact_reviewer(
    runtime: AgentRuntime,
    base_context: dict,
    summary: RepositorySummary,
    plan: dict,
    code_output: dict | None,
    docs_output: dict | None,
    dependency_output: dict | None,
    unavailable_evidence: list[str],
) -> AgentRecord:
    return await run_agent(
        runtime,
        agent_name=IMPACT_REVIEWER,
        system_prompt=IMPACT_REVIEWER_SYSTEM,
        user_prompt=impact_reviewer_prompt(
            base_context,
            summary,
            plan,
            code_output,
            docs_output,
            dependency_output,
            unavailable_evidence,
        ),
        response_schema=ImpactReviewerOutput,
        input_summary={
            "upstream_agents": ["code_analyst", "documentation_analyst", "dependency_analyst"],
            "unavailable_evidence": unavailable_evidence,
        },
    )


def degraded_report(base_context: dict, unavailable_evidence: list[str]) -> dict:
    """Minimal report used when the reviewer itself fails.

    We still surface what the deterministic layer knows rather than showing the
    user nothing, but the severity and confidence make the degradation obvious.
    """
    return {
        "overall_severity": "MEDIUM",
        "summary": (
            "The Impact Reviewer failed, so no consolidated report was produced. "
            "The findings below come from the deterministic repository analysis only."
        ),
        "affected_components": [],
        "documentation_updates": [],
        "recommended_tests": [],
        "recommended_actions": [
            "Re-run the analysis — the synthesis agent failed.",
            "Review the individual agent outputs in the execution view for partial findings.",
        ],
        "risks": ["Impact assessment is incomplete: the synthesis stage did not run."],
        "confirmed_findings": [],
        "likely_findings": [],
        "uncertain_findings": [
            f"{agent} evidence unavailable." for agent in unavailable_evidence
        ]
        or ["All findings unverified: synthesis did not run."],
        "contradictions": [],
        "unsupported_claims": [],
        "confidence": 0.2,
        "degraded": True,
    }
