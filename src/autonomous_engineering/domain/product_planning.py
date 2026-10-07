"""Product plans are distinct from autonomous coding execution tasks."""
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from autonomous_engineering.domain.base import DomainModel, NonBlank, Summary, UtcTimestamp

Title = Annotated[NonBlank, Field(max_length=200)]
EpicRef = Annotated[str, Field(pattern=r'^E[1-9][0-9]*$')]
TaskRef = Annotated[str, Field(pattern=r'^T[1-9][0-9]*$')]
ESTIMATE_NOTICE = 'Rough engineering effort estimates, not guaranteed delivery times.'


class EngineeringStatus(StrEnum):
    BACKLOG = 'backlog'
    PLANNED = 'planned'
    IN_PROGRESS = 'in_progress'
    REVIEW = 'review'
    DONE = 'done'


class Priority(StrEnum):
    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'
    URGENT = 'urgent'


class TechnicalArea(StrEnum):
    BACKEND = 'Backend'
    FRONTEND = 'Frontend'
    DATABASE = 'Database'
    DEVOPS = 'DevOps'
    QA = 'QA'
    GENERAL = 'General'


class AcceptanceCriterion(DomainModel):
    description: Summary


class DraftEpic(DomainModel):
    ref: EpicRef
    title: Title
    description: Summary


class DraftEngineeringTask(DomainModel):
    ref: TaskRef
    epic_ref: EpicRef
    title: Title
    description: Summary
    priority: Priority
    estimated_hours: float = Field(gt=0, le=24, allow_inf_nan=False)
    technical_area: TechnicalArea
    dependencies: tuple[TaskRef, ...] = Field(max_length=16)
    acceptance_criteria: tuple[AcceptanceCriterion, ...] = Field(min_length=1, max_length=10)


class ProductPlanDraft(DomainModel):
    title: Title
    summary: Summary
    assumptions: tuple[Summary, ...] = Field(max_length=12)
    epics: tuple[DraftEpic, ...] = Field(min_length=1, max_length=8)
    tasks: tuple[DraftEngineeringTask, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode='after')
    def coherent_plan(self) -> Self:
        epics = {epic.ref for epic in self.epics}
        tasks = {task.ref: task for task in self.tasks}
        if len(epics) != len(self.epics) or len(tasks) != len(self.tasks):
            raise ValueError('Epic and task references must be unique')
        if {task.epic_ref for task in self.tasks} != epics:
            raise ValueError('Every epic must have tasks and all tasks must reference an existing epic')
        for task in self.tasks:
            if len(set(task.dependencies)) != len(task.dependencies):
                raise ValueError('Dependencies must be unique')
            if task.ref in task.dependencies or not set(task.dependencies).issubset(tasks):
                raise ValueError('Dependencies must reference other tasks in this plan')
        visited, visiting = set(), set()
        def visit(ref):
            if ref in visiting:
                raise ValueError('Task dependencies must not contain cycles')
            if ref in visited:
                return
            visiting.add(ref)
            for dependency in tasks[ref].dependencies:
                visit(dependency)
            visiting.remove(ref)
            visited.add(ref)
        for ref in tasks:
            visit(ref)
        return self


class ProjectGoal(DomainModel):
    id: UUID
    project_id: UUID
    goal: Annotated[NonBlank, Field(max_length=12000)]
    created_at: UtcTimestamp


class Epic(DomainModel):
    id: UUID
    plan_id: UUID
    title: Title
    description: Summary


class TaskDependency(DomainModel):
    task_id: UUID


class EngineeringTask(DomainModel):
    id: UUID
    key: str
    project_id: UUID
    plan_id: UUID
    epic_id: UUID
    title: Title
    description: Summary
    status: EngineeringStatus
    priority: Priority
    estimated_hours: float = Field(gt=0, le=160, allow_inf_nan=False)
    technical_area: TechnicalArea
    dependencies: tuple[TaskDependency, ...]
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    created_at: UtcTimestamp
    revision: int = Field(ge=0)
    execution_run_id: UUID | None = None
    squad_id: UUID | None = None
    assignee_id: UUID | None = None


class ProjectPlan(DomainModel):
    id: UUID
    project_id: UUID
    title: Title
    summary: Summary
    assumptions: tuple[Summary, ...]
    epics: tuple[Epic, ...]
    tasks: tuple[EngineeringTask, ...]
    estimated_hours: float
    estimate_notice: str = ESTIMATE_NOTICE


class PlanRecord(DomainModel):
    goal: ProjectGoal
    status: Annotated[str, Field(pattern=r'^(queued|generating|ready|failed)$')]
    plan: ProjectPlan | None
    attempts: int = Field(ge=0, le=2)
    error: str | None
    model: str | None
