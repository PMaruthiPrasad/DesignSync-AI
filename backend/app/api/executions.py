"""Execution endpoints: status, progress events, and per-agent observability."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import AgentExecutionResponse, ExecutionEventResponse, ExecutionResponse
from app.services import events as events_service
from app.services import execution_service

router = APIRouter(prefix="/executions", tags=["executions"])


def _require_execution(db: Session, execution_id: str):
    execution = execution_service.get_execution(db, execution_id)
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return execution


@router.get("/{execution_id}", response_model=ExecutionResponse)
def get_execution(execution_id: str, db: Session = Depends(get_db)) -> ExecutionResponse:
    execution = _require_execution(db, execution_id)
    return execution_service.to_execution_response(db, execution)


@router.get("/{execution_id}/events", response_model=list[ExecutionEventResponse])
def get_events(
    execution_id: str,
    after_seq: int = Query(0, ge=0, description="Return only events after this sequence number"),
    db: Session = Depends(get_db),
) -> list[ExecutionEventResponse]:
    """Ordered progress events. The UI polls this with the last seq it has seen."""
    _require_execution(db, execution_id)
    return [
        ExecutionEventResponse(
            seq=event.seq,
            event_type=event.event_type,
            agent_name=event.agent_name,
            message=event.message,
            payload=json.loads(event.payload_json) if event.payload_json else None,
            created_at=event.created_at,
        )
        for event in events_service.list_events(db, execution_id, after_seq)
    ]


@router.get("/{execution_id}/agents", response_model=list[AgentExecutionResponse])
def get_agents(execution_id: str, db: Session = Depends(get_db)) -> list[AgentExecutionResponse]:
    """Full observability record for every agent in this execution."""
    _require_execution(db, execution_id)
    return [
        execution_service.to_agent_response(row)
        for row in execution_service.list_agent_executions(db, execution_id)
    ]
