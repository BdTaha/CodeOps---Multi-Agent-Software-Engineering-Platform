"""Real orchestration operations, without placeholder engineering agents."""

import logging
from datetime import datetime
from time import perf_counter
from typing import TypedDict

from autonomous_engineering.domain.base import utc_now
from autonomous_engineering.domain.execution import (
    AgentName,
    ExecutionError,
    ExecutionRecord,
    ExecutionStatus,
)
from autonomous_engineering.domain.results import ReportSummary
from autonomous_engineering.domain.tasks import TaskStatus
from autonomous_engineering.workflows.state import WorkflowState, WorkflowUpdate

logger = logging.getLogger(__name__)
UNAVAILABLE_CODE = "PLAN_APPROVAL_REQUIRED"


class GraphState(TypedDict):
    # One replace-only channel preserves cross-field validation atomically.
    snapshot: WorkflowState


def read_snapshot(state: GraphState) -> WorkflowState:
    """Revalidate node inputs, including JSON-deserialized snapshots."""
    return WorkflowState.model_validate(state["snapshot"])


def record_update(
    state: WorkflowState,
    update: WorkflowUpdate,
    *,
    operation: str,
    started_at: datetime,
    started_clock: float,
    output_summary: str,
    agent: AgentName = AgentName.SUPERVISOR,
    usage: dict | None = None,
) -> GraphState:
    """Measure this operation and append its record in the same state update."""
    ended_at = utc_now()
    duration = perf_counter() - started_clock
    attempt = 1 + max(
        (e.attempt for e in state.executions if e.agent == agent),
        default=0,
    )
    error = update.errors[-1] if update.errors else None
    record = ExecutionRecord(
        task_id=state.task.task_id,
        run_id=state.run_id,
        agent=agent,
        operation=operation,
        attempt=attempt,
        status=ExecutionStatus.FAILED if error else ExecutionStatus.SUCCEEDED,
        input_summary=f"operation={operation}; task_status={state.task.status}",
        output_summary=output_summary,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration,
        error=error,
        **(usage or {}),
    )
    values = update.model_dump(exclude_unset=True)
    values["executions"] = (*update.executions, record)
    updated = state.apply(WorkflowUpdate.model_validate(values), at=ended_at)
    logger.info(
        "Workflow node completed task_id=%s run_id=%s operation=%s status=%s duration_seconds=%.6f",
        state.task.task_id, state.run_id, operation, record.status, duration,
    )
    return {"snapshot": updated}


def supervisor(state: GraphState) -> GraphState:
    snapshot = read_snapshot(state)
    started_at, started_clock = utc_now(), perf_counter()
    if snapshot.task.status != TaskStatus.PENDING:
        raise ValueError("supervisor initialization requires a pending task")
    return record_update(
        snapshot,
        WorkflowUpdate(status=TaskStatus.RUNNING, current_agent=AgentName.SUPERVISOR),
        operation="initialize_task",
        started_at=started_at,
        started_clock=started_clock,
        output_summary="Task started; repository analysis is the next required capability.",
    )


def check_capability(state: GraphState) -> GraphState:
    snapshot = read_snapshot(state)
    started_at, started_clock = utc_now(), perf_counter()
    if snapshot.task.status != TaskStatus.RUNNING:
        raise ValueError("capability check requires a running task")
    if snapshot.plan is None:
        raise ValueError("developer capability check requires an implementation plan")
    error = ExecutionError(
        code=UNAVAILABLE_CODE,
        message="Planning stopped before development. Review the exact plan and explicitly approve its managed snapshot in the monitor to start the Developer Agent.",
        retryable=False,
    )
    return record_update(
        snapshot,
        WorkflowUpdate(current_agent=AgentName.SUPERVISOR, errors=(error,)),
        operation="check_developer",
        started_at=started_at,
        started_clock=started_clock,
        output_summary="Draft planning completed; human approval is required before code changes.",
    )


def finalize_failure(state: GraphState) -> GraphState:
    snapshot = read_snapshot(state)
    started_at, started_clock = utc_now(), perf_counter()
    if not snapshot.errors:
        raise ValueError("failure finalization requires a structured error")
    return record_update(
        snapshot,
        WorkflowUpdate(
            status=TaskStatus.FAILED,
            current_agent=None,
            report=ReportSummary(
                outcome=TaskStatus.FAILED,
                summary=snapshot.errors[-1].message,
                limitations=(
                    "Development, test execution, and review did not run.",
                    "Draft planning completed; approval has not been granted." if snapshot.plan is not None else "Planning did not complete.",
                    "Repository analysis completed." if snapshot.analysis is not None else "Repository analysis did not complete.",
                ),
            ),
        ),
        operation="finalize_failure",
        started_at=started_at,
        started_clock=started_clock,
        output_summary="Task finalized as failed with its recorded error and available results.",
    )
