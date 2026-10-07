import pytest
from pydantic import ValidationError

from autonomous_engineering.domain.results import (
    CodeChange,
    ImplementationPlan,
    PlanStep,
    ReportSummary,
    ReviewFinding,
    ReviewResults,
    TestCounts,
    TestExecution,
    TestResults,
)


@pytest.mark.parametrize(
    "path", ["../secret", "src/../../secret", "/etc/passwd", "C:\\secret", "\\\\host\\share", ".", "src\x00/file"]
)
def test_file_references_reject_absolute_or_escaping_paths(path) -> None:
    with pytest.raises(ValidationError):
        CodeChange(path=path, kind="modified", summary="Fix")


def test_windows_relative_reference_is_normalized() -> None:
    change = CodeChange(path="src\\module.py", kind="modified", summary="Fix")
    assert change.path == "src/module.py"


def execution(**updates) -> TestExecution:
    values = {
        "command": ("python", "-m", "pytest"),
        "exit_code": 0,
        "duration_seconds": 0.5,
        "output_summary": "One test passed",
    }
    values.update(updates)
    return TestExecution(**values)


def test_passing_results_do_not_invent_counts() -> None:
    results = TestResults(outcome="passed", executions=(execution(),), summary="Command passed")
    assert results.counts is None
    assert TestResults.model_validate_json(results.model_dump_json()) == results


@pytest.mark.parametrize(
    "values",
    [
        {"outcome": "passed"},
        {"outcome": "passed", "executions": (execution(exit_code=1),)},
        {"outcome": "passed", "executions": (execution(timed_out=True),)},
        {"outcome": "passed", "executions": (execution(),), "counts": {"passed": 0, "failed": 0, "skipped": 2}},
        {"outcome": "failed", "executions": (execution(),)},
        {"outcome": "error", "executions": (execution(),)},
        {"outcome": "skipped", "executions": (execution(),)},
        {"outcome": "skipped", "counts": {"passed": 0, "failed": 0, "skipped": 0}},
    ],
)
def test_results_reject_contradictory_or_missing_evidence(values) -> None:
    with pytest.raises(ValidationError):
        TestResults(summary="Outcome", **values)


def test_failed_error_and_skipped_outcomes_are_distinct() -> None:
    failed = TestResults(outcome="failed", executions=(execution(exit_code=1),), summary="Assertion failed")
    error = TestResults(
        outcome="error",
        executions=(execution(exit_code=None, timed_out=True, output_summary="Timeout"),),
        summary="Timed out",
    )
    skipped = TestResults(outcome="skipped", summary="No test command selected")
    assert len({failed.outcome, error.outcome, skipped.outcome}) == 3


@pytest.mark.parametrize("duration", [-1, float("inf"), float("nan")])
def test_test_duration_must_be_finite_and_nonnegative(duration) -> None:
    with pytest.raises(ValidationError):
        execution(duration_seconds=duration)


def test_missing_exit_code_requires_an_error() -> None:
    with pytest.raises(ValidationError):
        execution(exit_code=None)
    with pytest.raises(ValidationError):
        TestCounts(passed=-1, failed=0, skipped=0)


@pytest.mark.parametrize("severity", ["high", "critical"])
def test_serious_review_findings_cannot_be_approved(severity) -> None:
    finding = ReviewFinding(severity=severity, description="Bug", recommended_fix="Fix bug")
    with pytest.raises(ValidationError):
        ReviewResults(approved=True, summary="Approved", findings=(finding,))
    assert not ReviewResults(approved=False, summary="Fix required", findings=(finding,)).approved


def test_rejected_review_requires_findings_and_line_requires_file() -> None:
    with pytest.raises(ValidationError):
        ReviewResults(approved=False, summary="Rejected")
    with pytest.raises(ValidationError):
        ReviewFinding(severity="low", description="Bug", recommended_fix="Fix", line=2)


def test_plan_requires_steps_and_test_strategy() -> None:
    with pytest.raises(ValidationError):
        ImplementationPlan(problem_interpretation="Bug", steps=(), tests_to_run=("pytest",))
    with pytest.raises(ValidationError):
        ImplementationPlan(problem_interpretation="Bug", steps=(PlanStep(description="Fix"),), tests_to_run=())


@pytest.mark.parametrize("outcome", ["pending", "running"])
def test_report_cannot_claim_an_incomplete_outcome(outcome) -> None:
    with pytest.raises(ValidationError):
        ReportSummary(outcome=outcome, summary="Done")
