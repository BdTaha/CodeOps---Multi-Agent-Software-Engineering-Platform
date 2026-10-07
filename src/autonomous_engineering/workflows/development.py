"""Approved development with optional trusted-local tests; review remains pending."""

from pathlib import Path
from time import perf_counter
from typing import Callable
from langgraph.graph import StateGraph, START, END

from autonomous_engineering.agents.developer import Developer, DevelopmentProvider, approval_identity, workspace_reader
from autonomous_engineering.domain.development import FileEdit
from autonomous_engineering.tools.workspace_changes import review_diff
from autonomous_engineering.domain.results import CodeChange, DevelopmentArtifact
import hashlib
from autonomous_engineering.agents.planner import PlanningError
from autonomous_engineering.domain.base import utc_now
from autonomous_engineering.domain.execution import AgentName, ExecutionError
from autonomous_engineering.domain.results import ReportSummary, TestOutcome, TestResults
from autonomous_engineering.agents.tester import Tester, TestProcess
from autonomous_engineering.agents.reviewer import Reviewer, ReviewProvider
from autonomous_engineering.domain.tasks import TaskStatus
from autonomous_engineering.tools.repository import RepositoryError
from autonomous_engineering.workflows.nodes import GraphState, read_snapshot, record_update
from autonomous_engineering.workflows.state import WorkflowState, WorkflowUpdate


def develop_approved(state: WorkflowState, storage: Path, approved_id: str,
                     provider: DevelopmentProvider, *, test_process: TestProcess | None = None,
                     review_provider: ReviewProvider | None = None,
                     on_node_started: Callable[[str], None] | None = None,
                     on_node_completed: Callable[[str, WorkflowState], None] | None = None,
                     allow_repairs: bool = False, before_write=None) -> WorkflowState:
    """Accept only the running planning snapshot retained by the trusted caller."""
    state = WorkflowState.model_validate(state)
    if state.task.status != TaskStatus.RUNNING or state.plan is None or state.development_attempts:
        raise RepositoryError("INVALID_CONTINUATION", "Development requires an unused running planning snapshot.")
    graph = StateGraph(GraphState)
    assert state.plan is not None
    paths = tuple(dict.fromkeys(path for step in state.plan.steps for path in step.files))
    reader = workspace_reader(state, storage)
    inventory = reader.inventory().files
    originals = {path: reader.read_text(path) if path in inventory else None for path in paths}
    initial_receipt = approved_id
    def develop(snapshot):
        receipt = initial_receipt if snapshot.development_attempts == 0 else approval_identity(snapshot, storage)
        result = _develop(snapshot, storage, receipt, provider, before_write)
        changed = result["snapshot"]
        if changed.development is not None:
            edits, changes, hashes = [], [], {}
            present = reader.inventory().files
            for path, before in originals.items():
                after = reader.read_text(path) if path in present else None
                if before == after:
                    continue
                kind = "created" if before is None else "deleted" if after is None else "modified"
                edit = FileEdit(path=path, kind=kind, content=after, summary="Cumulative approved change")
                edits.append(review_diff(edit, before))
                changes.append(CodeChange(path=path, kind=kind, summary=edit.summary))
                hashes[path] = hashlib.sha256(after.encode()).hexdigest() if after is not None else None
            artifact = DevelopmentArtifact(approval_id=initial_receipt, approved_at=changed.development.approved_at,
                explanation=changed.development.explanation, changes=tuple(changes), diff="".join(edits), content_hashes=hashes, original_files=originals)
            result = {"snapshot": changed.apply(WorkflowUpdate(changes=artifact.changes, development=artifact))}
        return result
    def node(operation, action):
        def invoke(envelope):
            if on_node_started is not None:
                on_node_started(operation)
            result = action(read_snapshot(envelope))
            if on_node_completed is not None:
                on_node_completed(operation, result["snapshot"])
            return result
        return invoke
    graph.add_node("develop_implementation", node("develop_implementation", develop))
    graph.add_node("run_tests", node("run_tests", lambda snapshot: _test(snapshot, storage, test_process)))
    graph.add_node("review_changes", node("review_changes", lambda snapshot: _review(snapshot, storage, review_provider)))
    graph.add_node("finalize_development", node("finalize_development", _finalize))
    def supervise(snapshot):
        started, clock = utc_now(), perf_counter()
        retry = allow_repairs and snapshot.development_attempts < snapshot.max_development_attempts and (
            snapshot.tests is not None and snapshot.tests.outcome == TestOutcome.FAILED or
            snapshot.review is not None and not snapshot.review.approved)
        return record_update(snapshot, WorkflowUpdate(current_agent=AgentName.SUPERVISOR), operation="route_validation",
            started_at=started, started_clock=clock, output_summary="Repair within the approved scope." if retry else "Stop with recorded validation evidence.")
    def route(envelope):
        snapshot = read_snapshot(envelope)
        if allow_repairs and snapshot.development_attempts < snapshot.max_development_attempts and (
                snapshot.tests is not None and snapshot.tests.outcome == TestOutcome.FAILED or snapshot.review is not None and not snapshot.review.approved):
            return "develop_implementation"
        return "finalize_development"
    graph.add_node("route_validation", node("route_validation", supervise))
    graph.add_edge(START, "develop_implementation")
    graph.add_edge("develop_implementation", "run_tests")
    graph.add_edge("run_tests", "review_changes")
    graph.add_edge("review_changes", "route_validation")
    graph.add_conditional_edges("route_validation", route, ["develop_implementation", "finalize_development"])
    graph.add_edge("finalize_development", END)
    return WorkflowState.model_validate(graph.compile().invoke({"snapshot": state}, config={"recursion_limit": state.max_development_attempts * 5 + 3})["snapshot"])


def _develop(state: WorkflowState, storage: Path, approved_id: str,
             provider: DevelopmentProvider, before_write=None) -> GraphState:
    started_at, clock = utc_now(), perf_counter()
    try:
        artifact = Developer(provider, before_write).develop(state, storage, approved_id)
        update = WorkflowUpdate(current_agent=AgentName.DEVELOPER, changes=artifact.changes,
                                development=artifact, development_attempt_increment=1)
        summary = f"Applied {len(artifact.changes)} file edits to the approved snapshot; tests and review have not run."
    except (RepositoryError, PlanningError) as exc:
        update = WorkflowUpdate(current_agent=AgentName.DEVELOPER, development_attempt_increment=1,
            errors=(ExecutionError(code=exc.code, message=str(exc), retryable=getattr(exc, "retryable", False)),))
        summary = "Development did not complete; inspect the recorded error."
    return record_update(state, update, agent=AgentName.DEVELOPER, operation="develop_implementation",
                         started_at=started_at, started_clock=clock, output_summary=summary, usage=getattr(provider, "last_usage", None))


def _test(state: WorkflowState, storage: Path, process: TestProcess | None) -> GraphState:
    if state.development is None:
        return {"snapshot": state}
    started_at, clock = utc_now(), perf_counter()
    if process is None:
        results = TestResults(outcome=TestOutcome.SKIPPED,
            summary="Test execution was not authorized; generated changes remain untested.")
    else:
        try:
            results = Tester(process).run(state, storage)
        except RepositoryError as exc:
            return record_update(state, WorkflowUpdate(current_agent=AgentName.TESTER,
                errors=(ExecutionError(code=exc.code, message=str(exc)),)), agent=AgentName.TESTER,
                operation="run_tests", started_at=started_at, started_clock=clock, output_summary="Test workspace validation failed; no command ran.")
    error = ExecutionError(code="TEST_EXECUTION_ERROR" if results.outcome == TestOutcome.ERROR else "TESTS_FAILED",
        message=results.summary) if results.outcome in {TestOutcome.ERROR, TestOutcome.FAILED} else None
    return record_update(state, WorkflowUpdate(current_agent=AgentName.TESTER, tests=results,
        errors=(error,) if error else ()), agent=AgentName.TESTER, operation="run_tests",
        started_at=started_at, started_clock=clock, output_summary=results.summary)


def _review(state: WorkflowState, storage: Path, provider: ReviewProvider | None) -> GraphState:
    if state.tests is None or state.tests.outcome != TestOutcome.PASSED or provider is None:
        return {"snapshot": state}
    started_at, clock = utc_now(), perf_counter()
    try:
        review = Reviewer(provider).review(state, storage)
        error = None if review.approved else ExecutionError(code="REVIEW_REJECTED", message=review.summary)
        update = WorkflowUpdate(current_agent=AgentName.REVIEWER, review=review, errors=(error,) if error else ())
        summary = review.summary
    except (RepositoryError, PlanningError) as exc:
        update = WorkflowUpdate(current_agent=AgentName.REVIEWER,
            errors=(ExecutionError(code=exc.code, message=str(exc), retryable=getattr(exc, "retryable", False)),))
        summary = "Review did not complete; no approval was inferred."
    return record_update(state, update, agent=AgentName.REVIEWER, operation="review_changes",
        started_at=started_at, started_clock=clock, output_summary=summary, usage=getattr(provider, "last_usage", None))


def _finalize(developed: WorkflowState) -> GraphState:
    passed = developed.tests is not None and developed.tests.outcome == TestOutcome.PASSED
    success = passed and developed.review is not None and developed.review.approved
    error = None
    if success:
        summary = "Approved snapshot changes passed the configured test suite and received model review approval."
    elif developed.review is not None:
        summary = developed.review.summary
    elif developed.errors:
        summary = developed.errors[-1].message
    else:
        summary = "Review was not configured." if passed else "Passing test evidence is required before review."
        error = ExecutionError(code="REVIEW_NOT_CONFIGURED" if passed else "TEST_VALIDATION_REQUIRED", message=summary)
    status = TaskStatus.SUCCEEDED if success else TaskStatus.FAILED
    limitations = ["Changes exist only in the managed text snapshot; source repository is unchanged.",
                   "No original-source commit or pull request was performed."]
    if developed.review is not None:
        limitations.append("Model review covered changed files and supplied tests; it is not a correctness or security guarantee.")
    else:
        limitations.append("Review has not completed.")
    return record_update(developed, WorkflowUpdate(status=status, current_agent=None,
        errors=(error,) if error else (), report=ReportSummary(outcome=status,
            summary=summary, limitations=tuple(limitations))),
        operation="finalize_development", started_at=utc_now(), started_clock=perf_counter(),
        output_summary="Engineering continuation finalized from actual development, test, and review evidence.")
