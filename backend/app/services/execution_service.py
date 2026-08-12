"""Execution orchestration: run the workflow, record everything, persist results.

`POST /api/analyses/{id}/execute` returns immediately with an execution id and
schedules the workflow as an asyncio task. The client then polls the event log,
so a long analysis never holds an HTTP request open.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import AGENT_LABELS, ALL_AGENTS
from app.agents.base import AgentRecord, AgentRuntime
from app.database import session_scope
from app.llm.factory import get_provider
from app.models import (
    AgentExecution,
    Analysis,
    DocumentationFinding,
    Execution,
    ImpactFinding,
)
from app.schemas import (
    AgentExecutionResponse,
    ExecutionMetrics,
    ExecutionResponse,
    RepositorySummary,
)
from app.services import events
from app.services.metrics import compute_metrics
from app.orchestrator.graph import run_workflow

logger = logging.getLogger(__name__)

# Background tasks are kept referenced so they are not garbage collected
# mid-flight (asyncio only holds a weak reference to running tasks).
_BACKGROUND_TASKS: set[asyncio.Task] = set()


class DbRecorder:
    """Persists agent progress as it happens, so the UI can show it live."""

    def __init__(self, execution_id: str):
        self.execution_id = execution_id

    def on_agent_started(self, agent_name: str) -> None:
        events.emit(
            self.execution_id,
            events.AGENT_STARTED,
            f"{AGENT_LABELS.get(agent_name, agent_name)} started",
            agent_name=agent_name,
        )
        try:
            with session_scope() as db:
                row = _get_agent_row(db, self.execution_id, agent_name)
                row.status = "RUNNING"
                row.started_at = datetime.now(timezone.utc)
        except Exception:  # pragma: no cover - progress must not break the run
            logger.exception("Failed to record agent start for %s", agent_name)

    def on_agent_finished(self, record: AgentRecord) -> None:
        label = AGENT_LABELS.get(record.agent_name, record.agent_name)
        if record.succeeded:
            event_type, message = events.AGENT_COMPLETED, f"{label} completed"
        else:
            event_type, message = events.AGENT_FAILED, f"{label} failed: {record.error}"

        events.emit(
            self.execution_id,
            event_type,
            message,
            agent_name=record.agent_name,
            payload={
                "status": record.status,
                "duration_ms": record.duration_ms,
                "confidence": record.confidence,
                "total_tokens": record.total_tokens,
            },
        )
        try:
            with session_scope() as db:
                row = _get_agent_row(db, self.execution_id, record.agent_name)
                _apply_record(row, record)
        except Exception:  # pragma: no cover
            logger.exception("Failed to record agent completion for %s", record.agent_name)


def _get_agent_row(db: Session, execution_id: str, agent_name: str) -> AgentExecution:
    stmt = (
        select(AgentExecution)
        .where(AgentExecution.execution_id == execution_id)
        .where(AgentExecution.agent_name == agent_name)
    )
    row = db.execute(stmt).scalars().first()
    if row is None:
        row = AgentExecution(execution_id=execution_id, agent_name=agent_name)
        db.add(row)
    return row


def _apply_record(row: AgentExecution, record: AgentRecord) -> None:
    row.status = record.status
    row.started_at = record.started_at
    row.completed_at = record.completed_at
    row.duration_ms = record.duration_ms
    row.prompt_tokens = record.prompt_tokens
    row.completion_tokens = record.completion_tokens
    row.total_tokens = record.total_tokens
    row.estimated_cost = record.estimated_cost
    row.confidence = record.confidence
    row.model = record.model
    row.provider = record.provider
    row.system_prompt = record.system_prompt
    row.user_prompt = record.user_prompt
    row.input_data = json.dumps(record.input_data) if record.input_data else None
    row.output_data = json.dumps(record.output_data) if record.output_data else None
    row.error = record.error


# --------------------------------------------------------------------------
# Starting an execution
# --------------------------------------------------------------------------


def start_execution(db: Session, analysis: Analysis) -> Execution:
    """Create the execution record and its WAITING agent rows."""
    execution = Execution(
        analysis_id=analysis.id,
        status="RUNNING",
        concurrency_limit=analysis.concurrency_limit,
        parallel_agent_count=3,
    )
    db.add(execution)
    db.flush()

    # Seed every agent as WAITING so the graph renders complete from frame one.
    for agent_name in ALL_AGENTS:
        db.add(AgentExecution(execution_id=execution.id, agent_name=agent_name, status="WAITING"))

    analysis.status = "RUNNING"
    db.commit()
    db.refresh(execution)

    events.reset_seq(execution.id)
    events.emit(
        execution.id,
        events.EXECUTION_STARTED,
        f"Analysis started with concurrency limit {analysis.concurrency_limit}",
        payload={"concurrency_limit": analysis.concurrency_limit},
    )
    return execution


def schedule_execution(execution_id: str, analysis_id: str) -> asyncio.Task:
    """Run the workflow in the background and keep a strong reference to it."""
    task = asyncio.create_task(run_execution(execution_id, analysis_id))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


async def run_execution(execution_id: str, analysis_id: str) -> None:
    """Execute the workflow for one analysis and persist everything it produced."""
    started = time.perf_counter()

    try:
        with session_scope() as db:
            analysis = db.get(Analysis, analysis_id)
            if analysis is None:
                raise ValueError(f"Analysis {analysis_id} disappeared before execution")
            change_description = analysis.change_description
            summary_json = analysis.repository_summary_json
            mock_llm = analysis.mock_llm
            concurrency_limit = analysis.concurrency_limit

        summary = RepositorySummary.model_validate_json(summary_json)
        provider = get_provider(mock_override=mock_llm)
        runtime = AgentRuntime.create(
            provider, concurrency_limit=concurrency_limit, recorder=DbRecorder(execution_id)
        )

        state = await run_workflow(runtime, change_description, summary)
        duration_ms = int((time.perf_counter() - started) * 1000)

        _persist_results(execution_id, analysis_id, state, duration_ms)

        events.emit(
            execution_id,
            events.EXECUTION_COMPLETED,
            "Analysis complete",
            payload={"duration_ms": duration_ms},
        )

    except Exception as exc:
        logger.exception("Execution %s failed", execution_id)
        duration_ms = int((time.perf_counter() - started) * 1000)
        _mark_failed(execution_id, analysis_id, f"{type(exc).__name__}: {exc}", duration_ms)
        events.emit(
            execution_id,
            events.EXECUTION_FAILED,
            f"Analysis failed: {type(exc).__name__}",
        )


def _persist_results(execution_id: str, analysis_id: str, state, duration_ms: int) -> None:
    """Write metrics, findings and the final report."""
    records: list[AgentRecord] = state.get("agent_records", [])
    report = state.get("report") or {}

    durations = {r.agent_name: r.duration_ms for r in records}
    total_tokens = sum(r.total_tokens for r in records)
    total_cost = sum(r.estimated_cost for r in records)
    metrics = compute_metrics(durations, duration_ms, total_tokens, total_cost)

    # A run is only SUCCESS if every agent succeeded; otherwise it is PARTIAL —
    # the report exists but is explicitly incomplete.
    failed = [r.agent_name for r in records if not r.succeeded]
    status = "SUCCESS" if not failed else "PARTIAL"

    with session_scope() as db:
        execution = db.get(Execution, execution_id)
        analysis = db.get(Analysis, analysis_id)
        if execution is None or analysis is None:  # pragma: no cover
            return

        execution.status = status
        execution.completed_at = datetime.now(timezone.utc)
        execution.duration_ms = metrics.duration_ms
        execution.estimated_sequential_duration_ms = metrics.estimated_sequential_duration_ms
        execution.estimated_time_saved_ms = metrics.estimated_time_saved_ms
        execution.estimated_speedup = metrics.estimated_speedup
        execution.total_tokens = metrics.total_tokens
        execution.estimated_cost = metrics.estimated_cost
        execution.parallel_agent_count = metrics.parallel_agent_count
        if failed:
            execution.error = "Agents failed: " + ", ".join(failed)

        # Agent rows are written incrementally by DbRecorder; re-apply here so a
        # dropped progress write cannot leave a stale row behind.
        for record in records:
            _apply_record(_get_agent_row(db, execution_id, record.agent_name), record)

        analysis.status = status
        analysis.completed_at = datetime.now(timezone.utc)
        analysis.overall_severity = report.get("overall_severity")
        analysis.report_json = json.dumps(report)

        # Replace findings so a re-run does not accumulate duplicates.
        for existing in list(analysis.impact_findings):
            db.delete(existing)
        for existing in list(analysis.documentation_findings):
            db.delete(existing)

        for component in report.get("affected_components", []):
            db.add(
                ImpactFinding(
                    analysis_id=analysis_id,
                    component=component.get("component", "")[:300],
                    severity=component.get("severity", "MEDIUM"),
                    impact_type=_impact_type(component),
                    description=component.get("impact", ""),
                    evidence=component.get("evidence"),
                    confidence=float(component.get("confidence", 0.0)),
                )
            )

        for document in report.get("documentation_updates", []):
            db.add(
                DocumentationFinding(
                    analysis_id=analysis_id,
                    document=document.get("document", "")[:300],
                    status=document.get("status", "REVIEW"),
                    current_statement=document.get("current_statement"),
                    reason=document.get("reason", ""),
                    recommended_action=document.get("recommended_action", ""),
                    confidence=float(document.get("confidence", 0.0)),
                )
            )


def _impact_type(component: dict) -> str:
    """Classify a reviewed component for the findings table."""
    evidence = (component.get("evidence") or "").lower()
    if "contains the changed" in (component.get("impact") or "").lower():
        return "DIRECT"
    return "POTENTIAL_DOWNSTREAM" if "import" in evidence else "DIRECT"


def _mark_failed(execution_id: str, analysis_id: str, error: str, duration_ms: int) -> None:
    try:
        with session_scope() as db:
            execution = db.get(Execution, execution_id)
            if execution is not None:
                execution.status = "FAILED"
                execution.completed_at = datetime.now(timezone.utc)
                execution.duration_ms = duration_ms
                execution.error = error
            analysis = db.get(Analysis, analysis_id)
            if analysis is not None:
                analysis.status = "FAILED"
                analysis.completed_at = datetime.now(timezone.utc)
    except Exception:  # pragma: no cover
        logger.exception("Could not mark execution %s as failed", execution_id)


# --------------------------------------------------------------------------
# Response assembly
# --------------------------------------------------------------------------


def get_execution(db: Session, execution_id: str) -> Execution | None:
    return db.get(Execution, execution_id)


def list_agent_executions(db: Session, execution_id: str) -> list[AgentExecution]:
    stmt = (
        select(AgentExecution)
        .where(AgentExecution.execution_id == execution_id)
        .order_by(AgentExecution.started_at.is_(None), AgentExecution.started_at)
    )
    return list(db.execute(stmt).scalars())


def to_agent_response(row: AgentExecution) -> AgentExecutionResponse:
    return AgentExecutionResponse(
        id=row.id,
        agent_name=row.agent_name,
        status=row.status,
        started_at=row.started_at,
        completed_at=row.completed_at,
        duration_ms=row.duration_ms,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        total_tokens=row.total_tokens,
        estimated_cost=row.estimated_cost,
        confidence=row.confidence,
        model=row.model,
        provider=row.provider,
        system_prompt=row.system_prompt,
        user_prompt=row.user_prompt,
        input_data=json.loads(row.input_data) if row.input_data else None,
        output_data=json.loads(row.output_data) if row.output_data else None,
        error=row.error,
    )


def to_execution_response(db: Session, execution: Execution) -> ExecutionResponse:
    agents = [to_agent_response(row) for row in list_agent_executions(db, execution.id)]
    return ExecutionResponse(
        id=execution.id,
        analysis_id=execution.analysis_id,
        status=execution.status,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        error=execution.error,
        metrics=ExecutionMetrics(
            duration_ms=execution.duration_ms,
            estimated_sequential_duration_ms=execution.estimated_sequential_duration_ms,
            estimated_time_saved_ms=execution.estimated_time_saved_ms,
            estimated_speedup=execution.estimated_speedup,
            parallel_agent_count=execution.parallel_agent_count,
            concurrency_limit=execution.concurrency_limit,
            total_tokens=execution.total_tokens,
            estimated_cost=execution.estimated_cost,
        ),
        agents=agents,
    )
