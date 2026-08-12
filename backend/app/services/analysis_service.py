"""Analysis CRUD and response assembly."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Analysis, Execution
from app.schemas import (
    AnalysisCreateRequest,
    AnalysisDetailResponse,
    AnalysisSummaryResponse,
    DocumentationFindingResponse,
    ImpactFindingResponse,
    RepositorySummary,
)
from app.services.repo_analysis import analyze_repository
from app.services.zip_repository import resolve_repository_name, resolve_repository_path

DEMO_REPOSITORY_NAME = "sample-repository"
DEFAULT_CHANGE_DESCRIPTION = (
    "Changed discount calculation from customer purchase-history based to "
    "customer-segment based."
)


class RepositoryNotFoundError(ValueError):
    """The requested repository id does not exist."""


def resolve_repository(repository_id: str | None) -> tuple[str, Path]:
    """Resolve a repository id to `(name, path)`. `None` means the demo repo."""
    settings = get_settings()

    if not repository_id or repository_id == "demo":
        return DEMO_REPOSITORY_NAME, settings.demo_repository_path

    path = resolve_repository_path(repository_id)
    if path is None:
        raise RepositoryNotFoundError(f"Unknown repository id: {repository_id}")
    return resolve_repository_name(repository_id, fallback=path.name), path


def derive_name(change_description: str) -> str:
    """A short, human-readable analysis name from the change description."""
    text = " ".join(change_description.split())
    if len(text) <= 70:
        return text
    cut = text[:70].rsplit(" ", 1)[0]
    return f"{cut}…"


def create_analysis(db: Session, request: AnalysisCreateRequest) -> Analysis:
    """Create an analysis, running the deterministic repository pass up front.

    Repository analysis happens here rather than inside the workflow so that a
    bad repository fails fast at creation time with a clear error, instead of
    surfacing as a mysterious agent failure mid-run.
    """
    settings = get_settings()
    repository_name, repository_path = resolve_repository(request.repository_id)

    summary = analyze_repository(repository_path, name=repository_name)

    analysis = Analysis(
        name=request.name or derive_name(request.change_description),
        description=None,
        change_description=request.change_description,
        repository_name=repository_name,
        repository_path=str(repository_path),
        status="PENDING",
        mock_llm=settings.mock_llm if request.mock_llm is None else request.mock_llm,
        concurrency_limit=request.concurrency_limit or settings.default_concurrency_limit,
        repository_summary_json=summary.model_dump_json(),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def get_analysis(db: Session, analysis_id: str) -> Analysis | None:
    return db.get(Analysis, analysis_id)


def list_analyses(db: Session, limit: int = 100) -> list[Analysis]:
    stmt = select(Analysis).order_by(Analysis.created_at.desc()).limit(limit)
    return list(db.execute(stmt).scalars())


def latest_execution(db: Session, analysis_id: str) -> Execution | None:
    stmt = (
        select(Execution)
        .where(Execution.analysis_id == analysis_id)
        .order_by(Execution.started_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


# --------------------------------------------------------------------------
# Response assembly
# --------------------------------------------------------------------------


def to_summary_response(db: Session, analysis: Analysis) -> AnalysisSummaryResponse:
    execution = latest_execution(db, analysis.id)
    return AnalysisSummaryResponse(
        id=analysis.id,
        name=analysis.name,
        change_description=analysis.change_description,
        repository_name=analysis.repository_name,
        status=analysis.status,
        overall_severity=analysis.overall_severity,
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
        affected_component_count=len(analysis.impact_findings),
        documentation_update_count=len(analysis.documentation_findings),
        duration_ms=execution.duration_ms if execution else None,
    )


def to_detail_response(db: Session, analysis: Analysis) -> AnalysisDetailResponse:
    execution = latest_execution(db, analysis.id)

    report = json.loads(analysis.report_json) if analysis.report_json else None
    repository_summary = (
        RepositorySummary.model_validate_json(analysis.repository_summary_json)
        if analysis.repository_summary_json
        else None
    )

    return AnalysisDetailResponse(
        id=analysis.id,
        name=analysis.name,
        description=analysis.description,
        change_description=analysis.change_description,
        repository_name=analysis.repository_name,
        status=analysis.status,
        overall_severity=analysis.overall_severity,
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
        mock_llm=analysis.mock_llm,
        concurrency_limit=analysis.concurrency_limit,
        latest_execution_id=execution.id if execution else None,
        affected_component_count=len(analysis.impact_findings),
        documentation_update_count=len(analysis.documentation_findings),
        duration_ms=execution.duration_ms if execution else None,
        report=report,
        repository_summary=repository_summary,
        impact_findings=[
            ImpactFindingResponse.model_validate(f) for f in analysis.impact_findings
        ],
        documentation_findings=[
            DocumentationFindingResponse.model_validate(f)
            for f in analysis.documentation_findings
        ],
    )
