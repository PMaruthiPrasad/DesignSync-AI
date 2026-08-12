"""Structured output contracts for each agent.

Every agent returns validated JSON, never free-form prose. These models are the
schema handed to the LLM (`output_config.format`) *and* the validator applied to
whatever comes back, so a malformed response is a caught error rather than a
silently corrupt report.

Schema constraints (required by the structured-outputs feature):
  * `extra="forbid"` so the emitted schema carries `additionalProperties: false`
  * no numeric/length constraints (`ge`, `max_length`, ...) — unsupported
  * no recursive models
  * every field required, so the model cannot quietly omit one
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
Priority = Literal["HIGH", "MEDIUM", "LOW"]
ImpactType = Literal["DIRECT", "POTENTIAL_DOWNSTREAM"]
DocStatus = Literal["STALE", "LIKELY_STALE", "REVIEW", "CURRENT"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# Agent 1: Planner
# --------------------------------------------------------------------------


class PlannerOutput(StrictModel):
    """The investigation plan. The Planner scopes work; it does not analyse."""

    change_summary: str
    primary_area: str
    investigation_targets: list[str]
    reasoning: str
    confidence: float


# --------------------------------------------------------------------------
# Agent 2: Code Analyst
# --------------------------------------------------------------------------


class CodeFinding(StrictModel):
    file: str
    symbol: str
    severity: Severity
    impact_type: ImpactType
    explanation: str
    evidence: str
    confidence: float


class Breakage(StrictModel):
    file: str
    description: str
    severity: Severity
    confidence: float


class TestRecommendation(StrictModel):
    test_name: str
    reason: str
    affected_component: str
    priority: Priority


class CodeAnalystOutput(StrictModel):
    affected_components: list[str]
    code_findings: list[CodeFinding]
    potential_breakages: list[Breakage]
    recommended_tests: list[TestRecommendation]
    confidence: float


# --------------------------------------------------------------------------
# Agent 3: Documentation Analyst
# --------------------------------------------------------------------------


class DocumentationFindingOut(StrictModel):
    document: str
    section: str
    current_statement: str
    why_stale: str
    recommended_update: str
    status: DocStatus
    confidence: float


class DocsAnalystOutput(StrictModel):
    documentation_findings: list[DocumentationFindingOut]
    stale_documents: list[str]
    proposed_updates: list[str]
    confidence: float


# --------------------------------------------------------------------------
# Agent 4: Dependency Analyst
# --------------------------------------------------------------------------


class DependencyEdge(StrictModel):
    source: str
    target: str
    relationship: str


class DependencyRisk(StrictModel):
    module: str
    risk: str
    severity: Severity
    confidence: float


class DependencyAnalystOutput(StrictModel):
    dependencies: list[DependencyEdge]
    affected_modules: list[str]
    dependency_risks: list[DependencyRisk]
    confidence: float


# --------------------------------------------------------------------------
# Agent 5: Impact Reviewer
# --------------------------------------------------------------------------


class ReviewedComponent(StrictModel):
    component: str
    impact: str
    severity: Severity
    evidence: str
    confidence: float


class ReviewedDocument(StrictModel):
    document: str
    status: DocStatus
    reason: str
    recommended_action: str
    confidence: float


class ImpactReviewerOutput(StrictModel):
    """Final synthesis. Distinguishes confirmed / likely / uncertain evidence."""

    overall_severity: Severity
    summary: str
    affected_components: list[ReviewedComponent]
    documentation_updates: list[ReviewedDocument]
    recommended_tests: list[TestRecommendation]
    recommended_actions: list[str]
    risks: list[str]
    confirmed_findings: list[str]
    likely_findings: list[str]
    uncertain_findings: list[str]
    contradictions: list[str]
    unsupported_claims: list[str]
    confidence: float


AGENT_OUTPUT_SCHEMAS: dict[str, type[StrictModel]] = {
    "planner": PlannerOutput,
    "code_analyst": CodeAnalystOutput,
    "documentation_analyst": DocsAnalystOutput,
    "dependency_analyst": DependencyAnalystOutput,
    "impact_reviewer": ImpactReviewerOutput,
}
