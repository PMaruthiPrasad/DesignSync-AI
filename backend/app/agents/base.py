"""Shared agent execution wrapper.

Every agent goes through `run_agent`, which is where the cross-cutting concerns
live: concurrency limiting, timing, token/cost accounting, progress events,
persistence and — importantly — failure containment.

An agent that fails is recorded as FAILED with its real error and returns
`None` output. The workflow continues, and the Impact Reviewer is told which
evidence is missing. Failures are never silently swallowed.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from pydantic import BaseModel

from app.llm.base import LLMProvider


@dataclass
class AgentRecord:
    """Everything we observed about one agent run."""

    agent_name: str
    status: str = "WAITING"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int = 0

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float = 0.0
    confidence: float | None = None

    model: str | None = None
    provider: str | None = None
    system_prompt: str | None = None
    user_prompt: str | None = None

    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] | None = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "SUCCESS"


class AgentRecorder(Protocol):
    """Persistence + progress hooks, supplied by the execution service."""

    def on_agent_started(self, agent_name: str) -> None: ...

    def on_agent_finished(self, record: AgentRecord) -> None: ...


class NullRecorder:
    """No-op recorder, for unit tests that only care about the graph."""

    def on_agent_started(self, agent_name: str) -> None:  # pragma: no cover - trivial
        return None

    def on_agent_finished(self, record: AgentRecord) -> None:  # pragma: no cover - trivial
        return None


@dataclass
class AgentRuntime:
    """Services shared by every agent in one execution."""

    provider: LLMProvider
    semaphore: asyncio.Semaphore
    recorder: AgentRecorder = field(default_factory=NullRecorder)

    @classmethod
    def create(
        cls,
        provider: LLMProvider,
        concurrency_limit: int = 3,
        recorder: AgentRecorder | None = None,
    ) -> AgentRuntime:
        """Build a runtime with a bounded concurrency semaphore.

        The semaphore is what stops a fan-out from issuing unlimited concurrent
        LLM requests, and it is the knob that makes the parallelism visible:
        set it to 1 and the three "parallel" agents serialise.
        """
        limit = max(1, int(concurrency_limit))
        return cls(provider=provider, semaphore=asyncio.Semaphore(limit), recorder=recorder or NullRecorder())


async def run_agent(
    runtime: AgentRuntime,
    *,
    agent_name: str,
    system_prompt: str,
    user_prompt: str,
    response_schema: type[BaseModel],
    input_summary: dict[str, Any] | None = None,
) -> AgentRecord:
    """Execute one agent, capturing observability data and containing failure."""
    record = AgentRecord(
        agent_name=agent_name,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        input_data=input_summary or {},
    )

    # Acquire the concurrency slot *before* marking RUNNING, so recorded
    # durations measure real work rather than time spent queueing.
    async with runtime.semaphore:
        record.status = "RUNNING"
        record.started_at = datetime.now(timezone.utc)
        runtime.recorder.on_agent_started(agent_name)
        started = time.perf_counter()

        try:
            response = await runtime.provider.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_schema=response_schema,
                agent_name=agent_name,
            )
            # Re-validate here rather than trusting the provider. `run_agent` is
            # the single choke point every agent passes through, so enforcing
            # the contract at this layer means no provider — real, mock, or a
            # future one — can put a schema-invalid payload into a report.
            payload = response_schema.model_validate(json.loads(response.content)).model_dump()

            record.status = "SUCCESS"
            record.output_data = payload
            record.model = response.model
            record.provider = response.provider
            record.prompt_tokens = response.prompt_tokens
            record.completion_tokens = response.completion_tokens
            record.total_tokens = response.total_tokens
            record.estimated_cost = response.estimated_cost
            confidence = payload.get("confidence")
            record.confidence = float(confidence) if isinstance(confidence, (int, float)) else None

        except Exception as exc:
            # Contained, recorded, and reported downstream — never swallowed.
            record.status = "FAILED"
            record.output_data = None
            record.error = f"{type(exc).__name__}: {exc}"
            record.model = getattr(runtime.provider, "model", None)
            record.provider = getattr(runtime.provider, "name", None)

        finally:
            record.duration_ms = int((time.perf_counter() - started) * 1000)
            record.completed_at = datetime.now(timezone.utc)
            runtime.recorder.on_agent_finished(record)

    return record
