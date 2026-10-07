"""Graph construction and deterministic entry routing."""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pathlib import Path
from autonomous_engineering.agents.planner import PlanProvider

from autonomous_engineering.domain.tasks import TaskStatus
from autonomous_engineering.workflows.nodes import (
    GraphState,
    check_capability,
    finalize_failure,
    read_snapshot,
    supervisor,
)
from autonomous_engineering.domain.execution import ExecutionStatus
from autonomous_engineering.infrastructure.workspaces import WorkspacePreparer
from autonomous_engineering.tools.repository import InspectionLimits
from autonomous_engineering.workflows.repository_nodes import analyzer_node, preparation_node
from autonomous_engineering.workflows.streaming import observed_node
from autonomous_engineering.workflows.planner_nodes import planner_node


def route_entry(state: GraphState) -> str:
    snapshot = read_snapshot(state)
    if snapshot.task.status.terminal:
        return END
    if snapshot.task.status != TaskStatus.PENDING:
        raise ValueError("running tasks cannot be resumed without checkpoint support")
    return "supervisor"


def build_workflow(
    *, workspace_root: Path = Path(".workspaces"), limits: InspectionLimits | None = None,
    planner_provider: PlanProvider | None = None,
) -> CompiledStateGraph[GraphState, None, GraphState, GraphState]:
    """Build a finite graph; generation is supplied by the composition boundary."""
    graph = StateGraph(GraphState)
    bounds = limits or InspectionLimits()
    graph.add_node("supervisor", observed_node("supervisor", supervisor))
    graph.add_node("check_capability", observed_node("check_capability", check_capability))
    graph.add_node("prepare_workspace", observed_node("prepare_workspace", preparation_node(WorkspacePreparer(workspace_root, bounds))))
    graph.add_node("analyze_repository", observed_node("analyze_repository", analyzer_node(bounds)))
    graph.add_node("plan_implementation", observed_node("plan_implementation", planner_node(planner_provider, bounds)))
    graph.add_node("finalize_failure", observed_node("finalize_failure", finalize_failure))
    graph.add_conditional_edges(
        START, route_entry, {"supervisor": "supervisor", END: END}
    )
    graph.add_edge("supervisor", "prepare_workspace")

    def after_preparation(state: GraphState) -> str:
        return "finalize_failure" if read_snapshot(state).executions[-1].status == ExecutionStatus.FAILED else "analyze_repository"

    def after_analysis(state: GraphState) -> str:
        return "finalize_failure" if read_snapshot(state).executions[-1].status == ExecutionStatus.FAILED else "plan_implementation"

    def after_planning(state: GraphState) -> str:
        return "finalize_failure" if read_snapshot(state).executions[-1].status == ExecutionStatus.FAILED else "check_capability"

    graph.add_conditional_edges("prepare_workspace", after_preparation,
                               {"finalize_failure": "finalize_failure", "analyze_repository": "analyze_repository"})
    graph.add_conditional_edges("analyze_repository", after_analysis,
                               {"finalize_failure": "finalize_failure", "plan_implementation": "plan_implementation"})
    graph.add_conditional_edges("plan_implementation", after_planning,
                               {"finalize_failure": "finalize_failure", "check_capability": "check_capability"})
    graph.add_edge("check_capability", "finalize_failure")
    graph.add_edge("finalize_failure", END)
    return graph.compile()
