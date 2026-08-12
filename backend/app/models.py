"""SQLAlchemy ORM models.

Six tables:
  Analysis              one requested change-impact analysis
  Execution             one run of the agent workflow for an analysis
  AgentExecution        per-agent observability record (tokens, cost, output)
  ImpactFinding         a component affected by the change
  DocumentationFinding  a document that may have gone stale
  ExecutionEvent        ordered progress log, replayed by the UI
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Analysis(Base):
    """A requested analysis of one software change."""

    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_description: Mapped[str] = mapped_column(Text)
    repository_name: Mapped[str] = mapped_column(String(200))
    repository_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    overall_severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mock_llm: Mapped[bool] = mapped_column(default=True)
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    executions: Mapped[list[Execution]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", order_by="Execution.started_at"
    )
    impact_findings: Mapped[list[ImpactFinding]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    documentation_findings: Mapped[list[DocumentationFinding]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    # The Impact Reviewer's consolidated report, stored as JSON text.
    report_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Deterministic repository summary captured at analysis-creation time.
    repository_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class Execution(Base):
    """One run of the five-agent workflow."""

    __tablename__ = "executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="RUNNING", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_sequential_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_time_saved_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_speedup: Mapped[float | None] = mapped_column(Float, nullable=True)

    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    parallel_agent_count: Mapped[int] = mapped_column(Integer, default=3)
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=3)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    analysis: Mapped[Analysis] = relationship(back_populates="executions")
    agent_executions: Mapped[list[AgentExecution]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="AgentExecution.started_at",
    )
    events: Mapped[list[ExecutionEvent]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", order_by="ExecutionEvent.seq"
    )


class AgentExecution(Base):
    """Observability record for a single agent run."""

    __tablename__ = "agent_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("executions.id", ondelete="CASCADE"), index=True
    )
    agent_name: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20), default="WAITING")

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    input_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    execution: Mapped[Execution] = relationship(back_populates="agent_executions")


class ImpactFinding(Base):
    """A software component judged to be affected by the change."""

    __tablename__ = "impact_findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    component: Mapped[str] = mapped_column(String(300))
    severity: Mapped[str] = mapped_column(String(20))
    impact_type: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    analysis: Mapped[Analysis] = relationship(back_populates="impact_findings")


class DocumentationFinding(Base):
    """A document that may have become stale because of the change."""

    __tablename__ = "documentation_findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    document: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(30))
    current_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    recommended_action: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    analysis: Mapped[Analysis] = relationship(back_populates="documentation_findings")


class ExecutionEvent(Base):
    """Ordered progress event, polled by the execution page."""

    __tablename__ = "execution_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("executions.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer, index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    agent_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    execution: Mapped[Execution] = relationship(back_populates="events")
