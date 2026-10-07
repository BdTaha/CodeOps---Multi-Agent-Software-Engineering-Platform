"""Structured agent outputs; these contracts perform no agent work."""

from enum import StrEnum
from typing import Self

from pydantic import Field, NonNegativeFloat, NonNegativeInt, model_validator

from autonomous_engineering.domain.base import (
    DomainModel,
    NonBlank,
    RepositoryFile,
    Summary,
    UtcTimestamp,
)
from autonomous_engineering.domain.tasks import TaskStatus


class RepositoryAnalysis(DomainModel):
    languages: tuple[NonBlank, ...]
    frameworks: tuple[NonBlank, ...] = ()
    dependencies: tuple[NonBlank, ...] = ()
    important_files: tuple[RepositoryFile, ...] = ()
    relevant_files: tuple[RepositoryFile, ...] = ()
    architecture_summary: Summary
    inspected_file_count: NonNegativeInt | None = None
    top_level_directories: tuple[NonBlank, ...] = ()
    limitations: tuple[Summary, ...] = ()


class PlanStep(DomainModel):
    description: Summary
    files: tuple[RepositoryFile, ...] = ()


class ImplementationPlan(DomainModel):
    problem_interpretation: Summary
    steps: tuple[PlanStep, ...] = Field(min_length=1, max_length=12)
    risks: tuple[Summary, ...] = Field(default=(), max_length=12)
    tests_to_run: tuple[Summary, ...] = Field(min_length=1, max_length=12)
    # Planner-owned evidence provenance; these fields do not imply approval.
    context_files: tuple[RepositoryFile, ...] = ()
    limitations: tuple[Summary, ...] = ()


class ChangeKind(StrEnum):
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"


class CodeChange(DomainModel):
    path: RepositoryFile
    kind: ChangeKind
    summary: Summary
    # Actual text changes and their diff are carried by DevelopmentArtifact.


class DevelopmentArtifact(DomainModel):
    approval_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved_at: UtcTimestamp
    explanation: Summary
    changes: tuple[CodeChange, ...]
    diff: str
    content_hashes: dict[RepositoryFile, str | None] = Field(default_factory=dict)
    original_files: dict[RepositoryFile, str | None] = Field(default_factory=dict)
    repair_note: Summary | None = None
    limitations: tuple[Summary, ...] = (
        "Changes exist only in the managed text snapshot; source repository is unchanged.",
        "Development alone does not establish passing tests or review approval; consult the recorded downstream evidence.",
    )


class TestOutcome(StrEnum):
    __test__ = False  # Prevent pytest from treating an imported contract as a test.
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


class TestCounts(DomainModel):
    __test__ = False
    passed: NonNegativeInt
    failed: NonNegativeInt
    skipped: NonNegativeInt


class TestExecution(DomainModel):
    __test__ = False
    command: tuple[NonBlank, ...] = Field(min_length=1)
    exit_code: int | None
    duration_seconds: NonNegativeFloat = Field(allow_inf_nan=False)
    output_summary: Summary
    timed_out: bool = False
    error: Summary | None = None

    @model_validator(mode="after")
    def require_exit_or_error(self) -> Self:
        if self.exit_code is None and not (self.timed_out or self.error):
            raise ValueError("missing exit code requires timeout or execution error")
        return self


class TestResults(DomainModel):
    __test__ = False
    outcome: TestOutcome
    executions: tuple[TestExecution, ...] = ()
    # Unknown counts remain absent; command exit codes do not imply test counts.
    counts: TestCounts | None = None
    summary: Summary
    suspected_cause: Summary | None = None
    recommendation: Summary | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.outcome == TestOutcome.SKIPPED:
            if self.executions or self.counts is not None:
                raise ValueError("skipped execution must not contain measured results")
            return self
        if not self.executions:
            raise ValueError("test outcomes require execution evidence")
        execution_error = any(e.timed_out or e.error is not None for e in self.executions)
        command_failed = any(e.exit_code != 0 for e in self.executions)
        if self.outcome == TestOutcome.PASSED:
            if execution_error or command_failed:
                raise ValueError("passed tests require successful command execution")
            if self.counts is not None and (self.counts.failed or not self.counts.passed):
                raise ValueError("passed test counts require passes and no failures")
        elif self.outcome == TestOutcome.ERROR:
            if not execution_error:
                raise ValueError("error outcome requires an execution error or timeout")
        elif execution_error or not (
            command_failed or (self.counts is not None and self.counts.failed > 0)
        ):
            raise ValueError("failed outcome requires failure evidence without execution errors")
        return self


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReviewFinding(DomainModel):
    severity: Severity
    description: Summary
    recommended_fix: Summary
    file: RepositoryFile | None = None
    line: int | None = Field(default=None, ge=1)
    evidence: Summary | None = None

    @model_validator(mode="after")
    def require_file_for_line(self) -> Self:
        if self.line is not None and self.file is None:
            raise ValueError("a line reference requires a file")
        return self


class ReviewResults(DomainModel):
    approved: bool
    summary: Summary
    findings: tuple[ReviewFinding, ...] = Field(default=(), max_length=6)

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if self.approved and any(
            f.severity in {Severity.HIGH, Severity.CRITICAL} for f in self.findings
        ):
            raise ValueError("review cannot approve unresolved high or critical findings")
        if not self.approved and not self.findings:
            raise ValueError("rejected review requires actionable findings")
        return self


class ReportSummary(DomainModel):
    """Final narrative alongside structured results already held in workflow state."""

    outcome: TaskStatus
    summary: Summary
    limitations: tuple[Summary, ...] = ()

    @model_validator(mode="after")
    def require_terminal_outcome(self) -> Self:
        if not self.outcome.terminal:
            raise ValueError("report outcome must be terminal")
        return self
