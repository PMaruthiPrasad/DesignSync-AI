"""Analysis endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    AnalysisCreateRequest,
    AnalysisDetailResponse,
    AnalysisSummaryResponse,
    ExecuteResponse,
)
from app.services import analysis_service, execution_service
from app.services.analysis_service import RepositoryNotFoundError

router = APIRouter(prefix="/analyses", tags=["analyses"])


@router.post("", response_model=AnalysisDetailResponse, status_code=status.HTTP_201_CREATED)
def create_analysis(
    request: AnalysisCreateRequest, db: Session = Depends(get_db)
) -> AnalysisDetailResponse:
    """Create an analysis and run the deterministic repository pass."""
    try:
        analysis = analysis_service.create_analysis(db, request)
    except RepositoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Repository could not be analysed: {exc}",
        ) from exc

    return analysis_service.to_detail_response(db, analysis)


@router.get("", response_model=list[AnalysisSummaryResponse])
def list_analyses(db: Session = Depends(get_db)) -> list[AnalysisSummaryResponse]:
    return [
        analysis_service.to_summary_response(db, analysis)
        for analysis in analysis_service.list_analyses(db)
    ]


@router.get("/{analysis_id}", response_model=AnalysisDetailResponse)
def get_analysis(analysis_id: str, db: Session = Depends(get_db)) -> AnalysisDetailResponse:
    analysis = analysis_service.get_analysis(db, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    return analysis_service.to_detail_response(db, analysis)


@router.post(
    "/{analysis_id}/execute",
    response_model=ExecuteResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_analysis(analysis_id: str, db: Session = Depends(get_db)) -> ExecuteResponse:
    """Start the agent workflow and return immediately.

    The workflow runs as a background task; the client follows progress by
    polling `/api/executions/{id}/events`.

    This handler is `async` deliberately: it must execute on the event loop so
    that `asyncio.create_task` has a running loop to schedule the workflow on.
    A sync handler would run in a worker thread, where there is none.
    """
    analysis = analysis_service.get_analysis(db, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    if analysis.status == "RUNNING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This analysis is already running",
        )

    execution = execution_service.start_execution(db, analysis)
    execution_service.schedule_execution(execution.id, analysis.id)

    return ExecuteResponse(
        execution_id=execution.id, analysis_id=analysis.id, status=execution.status
    )
