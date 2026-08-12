"""Workflow state shared across the graph.

The list-valued keys use `operator.add` reducers. That is what lets the three
parallel branches write into the same state in the same superstep without
clobbering each other — LangGraph merges their partial updates instead of
raising a concurrent-write error.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from app.agents.base import AgentRecord, AgentRuntime
from app.schemas import RepositorySummary


class WorkflowState(TypedDict, total=False):
    """State threaded through the LangGraph workflow."""

    # --- inputs (set once, read by every node) -----------------------------
    runtime: AgentRuntime
    summary: RepositorySummary
    base_context: dict[str, Any]

    # --- planner output ----------------------------------------------------
    plan: dict[str, Any]

    # --- parallel branch outputs (each node writes its own key) ------------
    code_output: dict[str, Any] | None
    docs_output: dict[str, Any] | None
    dependency_output: dict[str, Any] | None

    # --- merged across branches -------------------------------------------
    agent_records: Annotated[list[AgentRecord], operator.add]
    unavailable_evidence: Annotated[list[str], operator.add]

    # --- final synthesis ---------------------------------------------------
    report: dict[str, Any] | None
