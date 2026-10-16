"""Validated snapshots and explicit sequential update semantics."""

from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator

from autonomous_engineering.domain.base import DomainModel, NonBlank, Summary, UtcTimestamp
from autonomous_engineering.domain.execution import AgentName, ExecutionError, ExecutionRecord
from autonomous_engineering.domain.results import (
    CodeChange,
    DevelopmentArtifact,
    ImplementationPlan,
    ReportSummary,
    RepositoryAnalysis,
    ReviewResults,
    TestOutcome,
    TestResults,
)
from autonomous_engineering.domain.tasks import TaskRecord, TaskStatus


class WorkflowUpdate(DomainModel):
    """Omitted result fields remain unchanged; explicit None clears a result."""

    status: TaskStatus | None = None
    current_agent: AgentName | None = None
    analysis: RepositoryAnalysis | None = None
    plan: ImplementationPlan | None = None
    changes: tuple[CodeChange, ...] = ()
    development: DevelopmentArtifact | None = None
    tests: TestResults | None = None
    review: ReviewResults | None = None
    report: ReportSummary | None = None
    executions: tuple[ExecutionRecord, ...] = ()
    errors: tuple[ExecutionError, ...] = ()
    development_attempt_increment: Literal[0, 1] = 0


class WorkflowState(DomainModel):
    schema_version: Literal[1] = 1
    task: TaskRecord
    run_id: UUID = Field(default_factory=uuid4)
    # Assigned by future workspace provisioning; source input stays in task.request.
    workspace_path: NonBlank | None = None
    workspace_notes: tuple[Summary, ...] = ()
    current_agent: AgentName | None = None
    development_attempts: NonNegativeInt = 0
    max_development_attempts: PositiveInt = 3
    analysis: RepositoryAnalysis | None = None
    plan: ImplementationPlan | None = None
    changes: tuple[CodeChange, ...] = ()
    development: DevelopmentArtifact | None = None
    tests: TestResults | None = None
    review: ReviewResults | None = None
    report: ReportSummary | None = None
    executions: tuple[ExecutionRecord, ...] = ()
    errors: tuple[ExecutionError, ...] = ()

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.development_attempts > self.max_development_attempts:
            raise ValueError("development attempt budget exceeded")
        if self.current_agent is not None and self.task.status != TaskStatus.RUNNING:
            raise ValueError("an active agent requires a running task")
        ids: set[UUID] = set()
        for execution in self.executions:
            if execution.task_id != self.task.task_id or execution.run_id != self.run_id:
                raise ValueError("execution belongs to a different task or run")
            if execution.execution_id in ids:
                raise ValueError("duplicate execution identity")
            ids.add(execution.execution_id)
        if len({change.path for change in self.changes}) != len(self.changes):
            raise ValueError("change paths must be unique")
        if self.development is not None and self.development.changes != self.changes:
            raise ValueError("development artifact must match recorded changes")
        if self.task.status.terminal:
            if self.current_agent is not None:
                raise ValueError("terminal tasks cannot have an active agent")
            if self.report is not None and self.report.outcome != self.task.status:
                raise ValueError("report outcome must match terminal task status")
        if self.task.status == TaskStatus.SUCCEEDED:
            if self.tests is None or self.tests.outcome != TestOutcome.PASSED:
                raise ValueError("successful workflow requires passing test evidence")
            if self.review is None or not self.review.approved:
                raise ValueError("successful workflow requires an approved review")
            if self.report is None or self.report.outcome != TaskStatus.SUCCEEDED:
                raise ValueError("successful workflow requires a success report")
        return self

    def apply(self, update: WorkflowUpdate, *, at: UtcTimestamp | None = None) -> Self:
        """Apply one node's update atomically, returning a new validated snapshot.

        Sequential semantics only. Phase 3 will adapt these rules to LangGraph;
        this method is not a concurrent reducer or a persistence transaction.
        """
        update = WorkflowUpdate.model_validate(update)
        if self.task.status.terminal:
            raise ValueError("terminal workflow snapshots cannot be updated")
        values = self.model_dump()
        if "status" in update.model_fields_set:
            if update.status is None:
                raise ValueError("task status cannot be cleared")
            values["task"] = self.task.transition(update.status, at=at)

        # Earlier-stage replacement invalidates downstream results first.
        if "analysis" in update.model_fields_set:
            values.update(plan=None, changes=(), development=None, tests=None, review=None, report=None)
        if "plan" in update.model_fields_set:
            values.update(changes=(), development=None, tests=None, review=None, report=None)
        # An attempt can fail before producing any replacement code. Its count
        # and error must not invalidate evidence about the last accepted artifact.
        if "changes" in update.model_fields_set or "development" in update.model_fields_set:
            values.update(development=None, tests=None, review=None, report=None)
        if "tests" in update.model_fields_set:
            values.update(review=None, report=None)
        if "review" in update.model_fields_set:
            values["report"] = None

        for name in ("current_agent", "analysis", "plan", "changes", "development", "tests", "review", "report"):
            if name in update.model_fields_set:
                values[name] = getattr(update, name)
        values["development_attempts"] += update.development_attempt_increment
        values["executions"] = self.executions + update.executions
        values["errors"] = self.errors + update.errors
        return type(self).model_validate(values)
