"""Organizational resources and planning capacity, never execution workers."""
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from autonomous_engineering.domain.base import DomainModel, UtcTimestamp
from autonomous_engineering.domain.product_planning import TechnicalArea, Title


class MemberSkill(DomainModel):
    technical_area: TechnicalArea
    proficiency: int = Field(ge=1, le=5)


class SquadInput(DomainModel):
    name: Title
    description: str = Field(default='', max_length=4000)
    technical_areas: tuple[TechnicalArea, ...] = Field(min_length=1, max_length=6)

    @model_validator(mode='after')
    def unique_areas(self) -> Self:
        if len(set(self.technical_areas)) != len(self.technical_areas):
            raise ValueError('Squad areas must be unique')
        return self


class Squad(SquadInput):
    id: UUID
    project_id: UUID
    created_at: UtcTimestamp
    revision: int = Field(ge=0)


class SquadEdit(SquadInput):
    revision: int = Field(ge=0)


class MemberInput(DomainModel):
    name: Title
    role: Title
    member_type: Literal['human', 'ai']
    squad_id: UUID
    skills: tuple[MemberSkill, ...] = Field(min_length=1, max_length=6)
    active: bool = True
    weekly_capacity_hours: float | None = Field(default=None, ge=0, le=168, allow_inf_nan=False)
    target_utilization: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)
    availability: Literal['available', 'busy', 'offline'] | None = None
    max_concurrent_tasks: int | None = Field(default=None, ge=1, le=100)
    future_execution_role: Literal['developer', 'tester', 'reviewer', 'general'] | None = None

    @model_validator(mode='after')
    def capacity_model(self) -> Self:
        if len({skill.technical_area for skill in self.skills}) != len(self.skills):
            raise ValueError('Member skills must be unique')
        if self.member_type == 'human':
            if self.weekly_capacity_hours is None or self.target_utilization is None:
                raise ValueError('Humans require weekly capacity and target utilization')
            if any(value is not None for value in (self.availability, self.max_concurrent_tasks, self.future_execution_role)):
                raise ValueError('Human members cannot use AI capacity fields')
        else:
            if self.weekly_capacity_hours is not None or self.target_utilization is not None:
                raise ValueError('AI members do not use weekly human hours')
            if any(value is None for value in (self.availability, self.max_concurrent_tasks, self.future_execution_role)):
                raise ValueError('AI members require availability, concurrency and future execution role')
        return self


class TeamMember(MemberInput):
    id: UUID
    project_id: UUID
    created_at: UtcTimestamp
    revision: int = Field(ge=0)


class MemberEdit(MemberInput):
    revision: int = Field(ge=0)


class MemberCapacity(DomainModel):
    member_id: UUID
    planned_load_hours: float
    assigned_task_count: int
    assignable_capacity_hours: float | None
    reserved_capacity_hours: float | None
    remaining_capacity_hours: float | None
    remaining_task_slots: int | None


class TaskAssignment(DomainModel):
    task_id: UUID
    squad_id: UUID | None
    assignee_id: UUID | None
    created_at: UtcTimestamp


class AssignmentInput(DomainModel):
    squad_id: UUID | None = None
    assignee_id: UUID | None = None
    revision: int = Field(ge=0)
    override_warnings: bool = False

    @model_validator(mode='after')
    def has_owner(self) -> Self:
        if self.squad_id is None and self.assignee_id is None:
            raise ValueError('Choose a squad or an assignee')
        return self


class SuggestedAssignment(DomainModel):
    task_id: UUID
    assignee_id: UUID
    revision: int = Field(ge=0)


class ApplyAssignments(DomainModel):
    project_revision: int = Field(ge=0)
    assignments: tuple[SuggestedAssignment, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode='after')
    def unique_tasks(self) -> Self:
        if len({item.task_id for item in self.assignments}) != len(self.assignments):
            raise ValueError('Each task may be assigned once')
        return self


class AssignmentRecommendation(DomainModel):
    task_id: UUID
    member_id: UUID
    squad_id: UUID
    score: float
    skill_proficiency: int
    fits_capacity: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    remaining_capacity_hours: float | None
    remaining_task_slots: int | None
