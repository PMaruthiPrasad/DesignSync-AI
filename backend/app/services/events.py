"""Execution progress events.

Progress is delivered by *polling* an ordered, persisted event log rather than
by SSE. The trade-off, deliberately made:

  + survives a page refresh and a reconnect (the log is in the database)
  + trivially testable — it is just a GET
  + immune to proxy/CDN buffering on the deployment platform
  - up to one poll interval (500 ms) of latency

At demo timescales that latency is invisible, and the reliability is worth it.
SSE is noted as a future improvement.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from sqlalchemy import select

from app.database import session_scope
from app.models import ExecutionEvent

# Event types the UI understands.
EXECUTION_STARTED = "execution_started"
AGENT_STARTED = "agent_started"
AGENT_COMPLETED = "agent_completed"
AGENT_FAILED = "agent_failed"
EXECUTION_COMPLETED = "execution_completed"
EXECUTION_FAILED = "execution_failed"

# Sequence numbers are allocated per execution. A lock keeps allocation safe if
# two analyses run concurrently in the same process.
_seq_lock = threading.Lock()
_seq_counters: dict[str, int] = {}


def next_seq(execution_id: str) -> int:
    with _seq_lock:
        value = _seq_counters.get(execution_id, 0) + 1
        _seq_counters[execution_id] = value
        return value


def reset_seq(execution_id: str) -> None:
    with _seq_lock:
        _seq_counters.pop(execution_id, None)


def emit(
    execution_id: str,
    event_type: str,
    message: str,
    agent_name: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Append an event to the log. Never raises into the workflow."""
    try:
        with session_scope() as db:
            db.add(
                ExecutionEvent(
                    execution_id=execution_id,
                    seq=next_seq(execution_id),
                    event_type=event_type,
                    agent_name=agent_name,
                    message=message,
                    payload_json=json.dumps(payload) if payload else None,
                )
            )
    except Exception:
        # Losing a progress event must never fail an analysis.
        pass


def list_events(db, execution_id: str, after_seq: int = 0) -> list[ExecutionEvent]:
    """Events after `after_seq`, in order."""
    stmt = (
        select(ExecutionEvent)
        .where(ExecutionEvent.execution_id == execution_id)
        .where(ExecutionEvent.seq > after_seq)
        .order_by(ExecutionEvent.seq)
    )
    return list(db.execute(stmt).scalars())
