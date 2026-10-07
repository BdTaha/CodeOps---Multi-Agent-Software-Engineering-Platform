"""Validated evidence associations. Providers cannot assign verification status."""
from typing import Literal
from uuid import UUID
from pydantic import Field, StrictBool
from autonomous_engineering.domain.base import DomainModel, Summary
from autonomous_engineering.domain.tasks import TaskRequest

MAPPER_VERSION = 'acceptance-evidence-v1'

class CriterionSnapshot(DomainModel):
    id: UUID
    description: Summary

class EvidenceSource(DomainModel):
    id: str = Field(min_length=1, max_length=180)
    evidence_type: Literal['automated_test', 'code_change', 'reviewer']
    reference: dict
    summary: Summary
    negative: bool = False
    executed: bool = False
    explicit_criteria: tuple[UUID, ...] = ()

class EvidenceAssociation(DomainModel):
    criterion_id: UUID
    source_id: str = Field(min_length=1, max_length=180)

class EvidenceMapping(DomainModel):
    associations: tuple[EvidenceAssociation, ...] = Field(default=(), max_length=120)

class EvidenceContext(DomainModel):
    task: TaskRequest
    criteria: tuple[CriterionSnapshot, ...]
    sources: tuple[EvidenceSource, ...]

class AcceptResult(DomainModel):
    revision: int = Field(ge=0)
    execution_task_id: UUID
    evidence_version: UUID | None = None
    unresolved_acknowledged: StrictBool = False
