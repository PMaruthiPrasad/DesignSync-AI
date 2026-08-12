"""Pydantic request and response models for the HTTP API.

These are the API contract. ORM objects are never returned directly, and no
setting or credential is ever serialised through them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
AgentStatus = Literal["WAITING", "RUNNING", "SUCCESS", "FAILED"]


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    llm_provider: str
    llm_model: str
    mock_llm: bool


# --------------------------------------------------------------------------
# Repository
# --------------------------------------------------------------------------


class SymbolInfo(BaseModel):
    name: str
    kind: Literal["function", "class", "method"]
    file: str
    line: int


class DocumentInfo(BaseModel):
    path: str
    headings: list[str] = Field(default_factory=list)
    excerpt: str = ""


class RepositorySummary(BaseModel):
    """Deterministic, AST-derived description of a repository.

    Produced without invoking an LLM and without importing or executing any of
    the analysed files.
    """

    name: str
    root: str
    files: list[str] = Field(default_factory=list)
    python_modules: list[str] = Field(default_factory=list)
    documentation_files: list[str] = Field(default_factory=list)
    test_files: list[str] = Field(default_factory=list)
    imports: dict[str, list[str]] = Field(default_factory=dict)
    import_graph: dict[str, list[str]] = Field(default_factory=dict)
    imported_by: dict[str, list[str]] = Field(default_factory=dict)
    symbols: list[SymbolInfo] = Field(default_factory=list)
    references: dict[str, list[str]] = Field(default_factory=dict)
    documents: list[DocumentInfo] = Field(default_factory=list)
    malformed_files: list[str] = Field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.files)


class DemoRepositoryResponse(BaseModel):
    repository_name: str
    default_change_description: str
    summary: RepositorySummary


class UploadedRepositoryResponse(BaseModel):
    repository_id: str
    repository_name: str
    summary: RepositorySummary


# --------------------------------------------------------------------------
# Analyses
# --------------------------------------------------------------------------


class AnalysisCreateRequest(BaseModel):
    change_description: str = Field(min_length=10, max_length=8000)
    name: str | None = Field(default=None, max_length=200)
    repository_id: str | None = Field(
        default=None,
        description="Uploaded repository id. Omit to use the bundled demo repository.",
    )
    mock_llm: bool | None = None
    concurrency_limit: int = Field(default=3, ge=1, le=8)

    @field_validator("change_description")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 10:
            raise ValueError("change_description must be at least 10 characters of real text")
        return stripped


class ImpactFindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    component: str
    severity: str
    impact_type: str
    description: str
    evidence: str | None = None
    confidence: float


class DocumentationFindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document: str
    status: str
    current_statement: str | None = None
    reason: str
    recommended_action: str
    confidence: float


class AnalysisSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    change_description: str
    repository_name: str
    status: str
    overall_severity: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    affected_component_count: int = 0
    documentation_update_count: int = 0
    duration_ms: int | None = None


class AnalysisDetailResponse(AnalysisSummaryResponse):
    description: str | None = None
    mock_llm: bool = True
    concurrency_limit: int = 3
    latest_execution_id: str | None = None
    report: dict[str, Any] | None = None
    repository_summary: RepositorySummary | None = None
    impact_findings: list[ImpactFindingResponse] = Field(default_factory=list)
    documentation_findings: list[DocumentationFindingResponse] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Executions
# --------------------------------------------------------------------------


class ExecuteResponse(BaseModel):
    execution_id: str
    analysis_id: str
    status: str


class AgentExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_name: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float = 0.0
    confidence: float | None = None
    model: str | None = None
    provider: str | None = None
    system_prompt: str | None = None
    user_prompt: str | None = None
    input_data: dict[str, Any] | None = None
    output_data: dict[str, Any] | None = None
    error: str | None = None


class ExecutionMetrics(BaseModel):
    """Parallel-execution metrics.

    `estimated_sequential_duration_ms` is exactly that — an estimate, computed
    as the sum of measured agent durations. It is labelled as such in the UI.
    """

    duration_ms: int | None = None
    estimated_sequential_duration_ms: int | None = None
    estimated_time_saved_ms: int | None = None
    estimated_speedup: float | None = None
    parallel_agent_count: int = 3
    concurrency_limit: int = 3
    total_tokens: int = 0
    estimated_cost: float = 0.0


class ExecutionResponse(BaseModel):
    id: str
    analysis_id: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    error: str | None = None
    metrics: ExecutionMetrics
    agents: list[AgentExecutionResponse] = Field(default_factory=list)


class ExecutionEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    event_type: str
    agent_name: str | None = None
    message: str
    payload: dict[str, Any] | None = None
    created_at: datetime


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------


class DashboardStats(BaseModel):
    total_analyses: int = 0
    successful_analyses: int = 0
    high_impact_changes: int = 0
    documentation_updates: int = 0
    average_duration_ms: float | None = None
    average_speedup: float | None = None
    recent_analyses: list[AnalysisSummaryResponse] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    detail: str
