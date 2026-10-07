"""Explicit board-to-engineering commands; no automatic dispatch."""
from pydantic import Field
from uuid import UUID
from autonomous_engineering.domain.base import DomainModel, NonBlank

ACTIVE_EXECUTION_PHASES = frozenset({'queued_planning', 'planning', 'awaiting_approval', 'queued_development', 'development'})


class StartExecution(DomainModel):
    revision: int = Field(ge=0)


class ReviewExecution(StartExecution):
    execution_task_id: UUID


class RequestChanges(ReviewExecution):
    feedback: NonBlank = Field(max_length=4000)
