"""Completed execution records; no logging or storage side effects."""

from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import Field, NonNegativeFloat, NonNegativeInt, PositiveInt, model_validator

from autonomous_engineering.domain.base import DomainModel, NonBlank, Summary, UtcTimestamp
from autonomous_engineering.domain.models import ModelInvocation


class AgentName(StrEnum):
    SUPERVISOR = "supervisor"
    REPOSITORY_ANALYZER = "repository_analyzer"
    PLANNER = "planner"
    DEVELOPER = "developer"
    TESTER = "tester"
    REVIEWER = "reviewer"
    REPORTER = "reporter"


class ExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ExecutionError(DomainModel):
    code: NonBlank
    message: Summary
    retryable: bool = False


class ExecutionRecord(DomainModel):
    execution_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    run_id: UUID
    agent: AgentName
    # An agent can execute several orchestration operations within one run.
    operation: NonBlank | None = None
    attempt: PositiveInt
    status: ExecutionStatus
    input_summary: Summary
    output_summary: Summary | None = None
    started_at: UtcTimestamp
    ended_at: UtcTimestamp
    # Supplied by the runner's monotonic clock, not derived from wall timestamps.
    duration_seconds: NonNegativeFloat = Field(allow_inf_nan=False)
    error: ExecutionError | None = None
    model: str | None = None
    input_tokens: NonNegativeInt | None = None
    output_tokens: NonNegativeInt | None = None
    model_invocations: tuple[ModelInvocation, ...] = ()

    @model_validator(mode="after")
    def validate_completion(self) -> Self:
        if self.ended_at < self.started_at:
            raise ValueError("execution end cannot precede start")
        if self.status == ExecutionStatus.FAILED and self.error is None:
            raise ValueError("failed execution requires a structured error")
        if self.status == ExecutionStatus.SUCCEEDED:
            if self.error is not None or self.output_summary is None:
                raise ValueError("successful execution requires output and no error")
        return self
