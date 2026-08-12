"""Dashboard statistics."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Analysis, DocumentationFinding, Execution
from app.schemas import DashboardStats
from app.services import analysis_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

RECENT_LIMIT = 5


@router.get("/stats", response_model=DashboardStats)
def get_stats(db: Session = Depends(get_db)) -> DashboardStats:
    total = db.execute(select(func.count(Analysis.id))).scalar_one()

    successful = db.execute(
        select(func.count(Analysis.id)).where(Analysis.status == "SUCCESS")
    ).scalar_one()

    high_impact = db.execute(
        select(func.count(Analysis.id)).where(
            Analysis.overall_severity.in_(["HIGH", "CRITICAL"])
        )
    ).scalar_one()

    documentation_updates = db.execute(
        select(func.count(DocumentationFinding.id))
    ).scalar_one()

    average_duration = db.execute(
        select(func.avg(Execution.duration_ms)).where(Execution.duration_ms.isnot(None))
    ).scalar()

    average_speedup = db.execute(
        select(func.avg(Execution.estimated_speedup)).where(
            Execution.estimated_speedup.isnot(None)
        )
    ).scalar()

    recent = analysis_service.list_analyses(db, limit=RECENT_LIMIT)

    return DashboardStats(
        total_analyses=total,
        successful_analyses=successful,
        high_impact_changes=high_impact,
        documentation_updates=documentation_updates,
        average_duration_ms=round(float(average_duration), 1) if average_duration else None,
        average_speedup=round(float(average_speedup), 2) if average_speedup else None,
        recent_analyses=[analysis_service.to_summary_response(db, a) for a in recent],
    )
