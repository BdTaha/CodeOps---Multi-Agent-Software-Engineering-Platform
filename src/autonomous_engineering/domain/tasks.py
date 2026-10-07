"""Task input, identity, and explicit lifecycle transitions."""

from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from autonomous_engineering.domain.base import DomainModel, NonBlank, UtcTimestamp, utc_now


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.FAILED, self.CANCELLED}


ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset(
        {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.SUCCEEDED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


class InvalidTaskTransition(ValueError):
    """Requested lifecycle transition is not permitted."""


class TaskRequest(DomainModel):
    # This is an input reference, not permission to access or execute this path.
    repository_path: NonBlank
    user_request: NonBlank = Field(max_length=20000)


class TaskRecord(DomainModel):
    task_id: UUID = Field(default_factory=uuid4)
    request: TaskRequest
    status: TaskStatus = TaskStatus.PENDING
    created_at: UtcTimestamp = Field(default_factory=utc_now)
    updated_at: UtcTimestamp = Field(default_factory=utc_now)
    started_at: UtcTimestamp | None = None
    finished_at: UtcTimestamp | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.started_at is not None and not (
            self.created_at <= self.started_at <= self.updated_at
        ):
            raise ValueError("started_at must be between created_at and updated_at")
        if self.status == TaskStatus.PENDING:
            if self.started_at is not None or self.finished_at is not None:
                raise ValueError("pending tasks cannot have execution timestamps")
        elif self.status == TaskStatus.RUNNING:
            if self.started_at is None or self.finished_at is not None:
                raise ValueError("running tasks require started_at and no finished_at")
        else:
            if self.finished_at is None or self.finished_at != self.updated_at:
                raise ValueError("terminal tasks require finished_at equal to updated_at")
            if self.status != TaskStatus.CANCELLED and self.started_at is None:
                raise ValueError("completed tasks must have started")
            if self.finished_at < (self.started_at or self.created_at):
                raise ValueError("finished_at cannot precede task creation or start")
        return self

    def transition(
        self, target: TaskStatus, *, at: UtcTimestamp | None = None
    ) -> Self:
        target = TaskStatus(target)
        if target not in ALLOWED_TRANSITIONS[self.status]:
            raise InvalidTaskTransition(f"cannot transition {self.status} to {target}")
        timestamp = utc_now() if at is None else at
        # Validate timezone awareness before comparing or changing timestamps.
        values = self.model_dump()
        values["updated_at"] = timestamp
        checked = type(self).model_validate(values)
        if checked.updated_at < self.updated_at:
            raise ValueError("transition timestamp cannot move backwards")
        values["status"] = target
        if target == TaskStatus.RUNNING:
            values["started_at"] = timestamp
        if target.terminal:
            values["finished_at"] = timestamp
        return type(self).model_validate(values)
