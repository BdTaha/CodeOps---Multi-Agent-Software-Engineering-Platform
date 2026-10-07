"""Adapt workspace preparation and repository analysis to graph updates."""

from collections.abc import Callable
from pathlib import Path
from time import perf_counter

from autonomous_engineering.agents.repository_analyzer import RepositoryAnalyzer
from autonomous_engineering.domain.base import utc_now
from autonomous_engineering.domain.execution import AgentName, ExecutionError
from autonomous_engineering.infrastructure.workspaces import WorkspacePreparer
from autonomous_engineering.tools.repository import InspectionLimits, RepositoryError, RepositoryReader
from autonomous_engineering.workflows.nodes import GraphState, read_snapshot, record_update
from autonomous_engineering.workflows.state import WorkflowState, WorkflowUpdate


def preparation_node(preparer: WorkspacePreparer) -> Callable[[GraphState], GraphState]:
    def prepare_workspace(state: GraphState) -> GraphState:
        snapshot = read_snapshot(state)
        started_at, started_clock = utc_now(), perf_counter()
        if snapshot.workspace_path is not None:
            raise ValueError("fresh tasks cannot supply a preassigned workspace")
        try:
            prepared = preparer.prepare(Path(snapshot.task.request.repository_path), snapshot.run_id)
            values = snapshot.model_dump()
            # Only the trusted provisioner assigns workspace identity/metadata.
            values.update(workspace_path=str(prepared.root), workspace_notes=prepared.notes)
            snapshot = WorkflowState.model_validate(values)
            update = WorkflowUpdate()
            summary = "Created an isolated, bounded text snapshot of the source repository."
        except RepositoryError as exc:
            update = WorkflowUpdate(errors=(ExecutionError(code=exc.code, message=str(exc)),))
            summary = "Repository snapshot preparation failed; analyzer was not invoked."
        return record_update(snapshot, update, operation="prepare_workspace",
                             started_at=started_at, started_clock=started_clock, output_summary=summary)
    return prepare_workspace


def analyzer_node(limits: InspectionLimits) -> Callable[[GraphState], GraphState]:
    analyzer = RepositoryAnalyzer()

    def analyze_repository(state: GraphState) -> GraphState:
        snapshot = read_snapshot(state)
        started_at, started_clock = utc_now(), perf_counter()
        if snapshot.workspace_path is None:
            raise ValueError("repository analysis requires a prepared workspace")
        try:
            result = analyzer.analyze(RepositoryReader(Path(snapshot.workspace_path), limits),
                                      snapshot.task.request.user_request)
            values = result.model_dump()
            values["limitations"] = snapshot.workspace_notes + result.limitations
            update = WorkflowUpdate(current_agent=AgentName.REPOSITORY_ANALYZER,
                                    analysis=type(result).model_validate(values))
            summary = f"Inspected {result.inspected_file_count} text files; returned observed layout and declared dependencies."
        except RepositoryError as exc:
            update = WorkflowUpdate(current_agent=AgentName.REPOSITORY_ANALYZER,
                                    errors=(ExecutionError(code=exc.code, message=str(exc)),))
            summary = "Repository analysis failed with a bounded access error."
        return record_update(snapshot, update, agent=AgentName.REPOSITORY_ANALYZER,
                             operation="analyze_repository", started_at=started_at,
                             started_clock=started_clock, output_summary=summary)
    return analyze_repository
