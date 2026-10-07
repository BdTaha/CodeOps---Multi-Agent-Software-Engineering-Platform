"""Planning adapter: record provider/access failures without invented output."""

from collections.abc import Callable
from pathlib import Path
from time import perf_counter

from autonomous_engineering.agents.planner import PlanProvider, Planner, PlanningError
from autonomous_engineering.domain.base import utc_now
from autonomous_engineering.domain.execution import AgentName, ExecutionError
from autonomous_engineering.tools.repository import InspectionLimits, RepositoryError, RepositoryReader
from autonomous_engineering.workflows.nodes import GraphState, read_snapshot, record_update
from autonomous_engineering.workflows.state import WorkflowUpdate


def planner_node(provider: PlanProvider | None, limits: InspectionLimits) -> Callable[[GraphState], GraphState]:
    def plan_implementation(state: GraphState) -> GraphState:
        snapshot = read_snapshot(state)
        started_at, started_clock = utc_now(), perf_counter()
        if snapshot.workspace_path is None or snapshot.analysis is None:
            raise ValueError("planning requires a prepared workspace and repository analysis")
        try:
            if provider is None:
                raise PlanningError("PLANNER_NOT_CONFIGURED", "Configure an LLM provider to generate an implementation plan.")
            result = Planner(provider).plan(RepositoryReader(Path(snapshot.workspace_path), limits),
                                            snapshot.task.request, snapshot.analysis)
            update = WorkflowUpdate(current_agent=AgentName.PLANNER, plan=result)
            summary = f"Generated a draft with {len(result.steps)} steps and {len(result.tests_to_run)} proposed test checks; no code changed."
        except (PlanningError, RepositoryError) as exc:
            update = WorkflowUpdate(current_agent=AgentName.PLANNER, errors=(ExecutionError(
                code=exc.code, message=str(exc), retryable=getattr(exc, "retryable", False),
            ),))
            summary = "Planning did not complete; no implementation plan was stored."
        return record_update(snapshot, update, agent=AgentName.PLANNER,
                             operation="plan_implementation", started_at=started_at,
                             started_clock=started_clock, output_summary=summary, usage=getattr(provider, "last_usage", None))
    return plan_implementation
