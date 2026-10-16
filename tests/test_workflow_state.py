from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from autonomous_engineering.domain.execution import ExecutionError, ExecutionRecord
from autonomous_engineering.domain.results import (
    CodeChange,
    ImplementationPlan,
    PlanStep,
    ReportSummary,
    RepositoryAnalysis,
    ReviewResults,
    TestExecution,
    TestResults,
)
from autonomous_engineering.domain.tasks import TaskRecord, TaskRequest, TaskStatus
from autonomous_engineering.workflows.state import WorkflowState, WorkflowUpdate

NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


@pytest.fixture
def state() -> WorkflowState:
    task = TaskRecord(
        request=TaskRequest(repository_path="repo", user_request="Fix bug"),
        created_at=NOW, updated_at=NOW,
    ).transition(TaskStatus.RUNNING, at=NOW)
    return WorkflowState(
        task=task,
        analysis=RepositoryAnalysis(languages=("Python",), architecture_summary="Small service"),
        plan=ImplementationPlan(
            problem_interpretation="Bug", steps=(PlanStep(description="Fix bug"),), tests_to_run=("pytest",),
        ),
        changes=(CodeChange(path="app.py", kind="modified", summary="Fix bug"),),
        tests=TestResults(
            outcome="passed", summary="Tests passed",
            executions=(TestExecution(command=("pytest",), exit_code=0, duration_seconds=0.1, output_summary="Passed"),),
        ),
        review=ReviewResults(approved=True, summary="Approved"),
        report=ReportSummary(outcome="succeeded", summary="Fixed"),
    )


def record(state, **updates) -> ExecutionRecord:
    values = {
        "task_id": state.task.task_id, "run_id": state.run_id, "agent": "tester",
        "attempt": 1, "status": "succeeded", "input_summary": "Run tests",
        "output_summary": "Passed", "started_at": NOW, "ended_at": NOW,
        "duration_seconds": 0.1,
    }
    values.update(updates)
    return ExecutionRecord(**values)


def test_state_round_trip_preserves_nested_types_and_identity(state) -> None:
    restored = WorkflowState.model_validate_json(state.model_dump_json())
    assert restored == state
    assert isinstance(restored.task, TaskRecord)
    assert restored.run_id == state.run_id
    assert restored.schema_version == 1


def test_history_and_errors_append_without_mutating_original(state) -> None:
    first, second = record(state), record(state, attempt=2)
    error = ExecutionError(code="TIMEOUT", message="Timeout", retryable=True)
    updated = state.apply(WorkflowUpdate(executions=(first,), errors=(error,)))
    updated = updated.apply(WorkflowUpdate(executions=(second,)))
    assert updated.executions == (first, second)
    assert updated.errors == (error,)
    assert state.executions == ()
    assert state.errors == ()


@pytest.mark.parametrize("field", ["task_id", "run_id"])
def test_history_rejects_foreign_identity(state, field) -> None:
    with pytest.raises(ValidationError):
        state.apply(WorkflowUpdate(executions=(record(state, **{field: uuid4()}),)))


def test_duplicate_execution_id_is_rejected(state) -> None:
    event = record(state)
    updated = state.apply(WorkflowUpdate(executions=(event,)))
    with pytest.raises(ValidationError):
        updated.apply(WorkflowUpdate(executions=(event,)))


@pytest.mark.parametrize(
    "field,cleared",
    [
        ("analysis", ("plan", "changes", "tests", "review", "report")),
        ("plan", ("changes", "tests", "review", "report")),
        ("changes", ("tests", "review", "report")),
        ("tests", ("review", "report")),
        ("review", ("report",)),
    ],
)
def test_result_replacement_invalidates_downstream_evidence(state, field, cleared) -> None:
    updated = state.apply(WorkflowUpdate(**{field: getattr(state, field)}))
    for name in cleared:
        assert getattr(updated, name) == (() if name == "changes" else None)
    assert getattr(state, field) is not None


def test_omitted_fields_are_preserved_and_explicit_none_clears(state) -> None:
    assert state.apply(WorkflowUpdate()).tests == state.tests
    update = WorkflowUpdate.model_validate_json(WorkflowUpdate(tests=None).model_dump_json(exclude_unset=True))
    updated = state.apply(update)
    assert updated.tests is None
    assert updated.analysis == state.analysis


def test_new_development_attempt_retains_evidence_and_enforces_budget(state) -> None:
    updated = state.apply(WorkflowUpdate(current_agent="developer", development_attempt_increment=1))
    assert updated.development_attempts == 1
    assert updated.tests == state.tests
    assert updated.review == state.review
    assert updated.report == state.report
    for _ in range(2):
        updated = updated.apply(WorkflowUpdate(development_attempt_increment=1))
    with pytest.raises(ValidationError):
        updated.apply(WorkflowUpdate(development_attempt_increment=1))
    assert updated.development_attempts == 3


def test_success_requires_test_review_and_report_evidence(state) -> None:
    succeeded = state.apply(WorkflowUpdate(status="succeeded"), at=NOW + timedelta(seconds=1))
    assert succeeded.task.status == TaskStatus.SUCCEEDED
    for field in ("tests", "review", "report"):
        missing = state.apply(WorkflowUpdate(**{field: None}))
        with pytest.raises(ValidationError):
            missing.apply(WorkflowUpdate(status="succeeded"), at=NOW + timedelta(seconds=1))


def test_skipped_tests_cannot_support_success(state) -> None:
    with pytest.raises(ValidationError):
        state.apply(WorkflowUpdate(
            status="succeeded", tests=TestResults(outcome="skipped", summary="Not run"),
            review=state.review, report=state.report,
        ), at=NOW + timedelta(seconds=1))


def test_active_agent_must_be_cleared_before_finishing(state) -> None:
    active = state.apply(WorkflowUpdate(current_agent="reporter"))
    with pytest.raises(ValidationError):
        active.apply(WorkflowUpdate(status="succeeded"), at=NOW + timedelta(seconds=1))
    completed = active.apply(WorkflowUpdate(status="succeeded", current_agent=None), at=NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match="terminal"):
        completed.apply(WorkflowUpdate())


def test_failure_can_be_reported_without_test_or_review_results(state) -> None:
    failed = state.apply(WorkflowUpdate(
        status="failed", tests=None, review=None,
        report=ReportSummary(outcome="failed", summary="Repository could not be inspected"),
        errors=(ExecutionError(code="REPO_ERROR", message="Cannot inspect"),),
    ), at=NOW + timedelta(seconds=1))
    assert failed.task.status == TaskStatus.FAILED
    assert failed.tests is None


def test_mismatched_terminal_report_is_rejected(state) -> None:
    with pytest.raises(ValidationError):
        state.apply(WorkflowUpdate(status="failed"), at=NOW + timedelta(seconds=1))


@pytest.mark.parametrize(
    "updates",
    [
        {"status": "failed"},
        {"status": "succeeded", "error": ExecutionError(code="BUG", message="Bug")},
        {"ended_at": NOW - timedelta(seconds=1)},
        {"started_at": NOW.replace(tzinfo=None)},
        {"duration_seconds": float("inf")},
        {"attempt": 0},
    ],
)
def test_execution_record_rejects_invalid_completion(state, updates) -> None:
    with pytest.raises(ValidationError):
        record(state, **updates)


def test_failed_execution_and_zero_duration_are_valid(state) -> None:
    event = record(state, status="failed", output_summary=None, duration_seconds=0,
                   error=ExecutionError(code="LLM_ERROR", message="Provider unavailable"))
    assert event.duration_seconds == 0
    assert event.error.retryable is False


def test_pending_task_can_be_started_or_cancelled_but_cannot_have_active_agent() -> None:
    initial = WorkflowState(task=TaskRecord(
        request=TaskRequest(repository_path="repo", user_request="Fix"),
        created_at=NOW, updated_at=NOW,
    ))
    with pytest.raises(ValidationError):
        initial.apply(WorkflowUpdate(current_agent="supervisor"))
    running = initial.apply(WorkflowUpdate(status="running", current_agent="supervisor"), at=NOW)
    cancelled = initial.apply(WorkflowUpdate(status="cancelled"), at=NOW)
    assert running.current_agent == "supervisor"
    assert cancelled.task.status == TaskStatus.CANCELLED
    assert initial.task.status == TaskStatus.PENDING


def test_changes_replace_current_diff_instead_of_accumulating_duplicate_files(state) -> None:
    change = CodeChange(path="new.py", kind="created", summary="New helper")
    updated = state.apply(WorkflowUpdate(changes=(change,)))
    assert updated.changes == (change,)
    with pytest.raises(ValidationError):
        state.apply(WorkflowUpdate(changes=(change, change)))


def test_failed_and_rejected_evidence_cannot_support_workflow_success(state) -> None:
    from autonomous_engineering.domain.results import ReviewFinding

    failed_tests = TestResults(
        outcome="failed", summary="Assertion failed",
        executions=(TestExecution(command=("pytest",), exit_code=1,
                                 duration_seconds=0.1, output_summary="Failed"),),
    )
    rejected = ReviewResults(
        approved=False, summary="Needs fix",
        findings=(ReviewFinding(severity="high", description="Bug", recommended_fix="Fix"),),
    )
    for tests, review in ((failed_tests, state.review), (state.tests, rejected)):
        with pytest.raises(ValidationError):
            state.apply(WorkflowUpdate(status="succeeded", tests=tests,
                                       review=review, report=state.report), at=NOW)
