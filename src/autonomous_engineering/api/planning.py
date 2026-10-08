"""Goal planning and board status changes; linked execution has explicit review gates."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from autonomous_engineering.domain.base import DomainModel, NonBlank
from autonomous_engineering.domain.product_planning import EngineeringStatus, ProductPlanDraft
from autonomous_engineering.infrastructure.planning_store import PlanningConflict


class NewProjectGoal(DomainModel):
    goal: Annotated[NonBlank, Field(max_length=12000)]


class StatusChange(DomainModel):
    status: EngineeringStatus
    revision: int = Field(ge=0)


class DraftEdit(DomainModel):
    revision: int = Field(ge=0)
    draft: ProductPlanDraft


class PlanApproval(DomainModel):
    revision: int = Field(ge=0)


def planning_router(store):
    router = APIRouter(tags=['Product planning'])
    def origin(request):
        if request.headers.get('origin') not in {None, str(request.base_url).rstrip('/')}:
            raise HTTPException(403, 'Requests must originate from this local workspace.')
    def project(project_id):
        if store.project(project_id) is None:
            raise HTTPException(404, 'Project not found.')
    def task(task_id):
        found = store.task(task_id)
        if found is None:
            raise HTTPException(404, 'Engineering task not found.')
        return found

    @router.post('/projects/{project_id}/plans', status_code=202)
    def create_plan(project_id: UUID, body: NewProjectGoal, request: Request):
        origin(request)
        project(project_id)
        try:
            return store.enqueue(project_id, body.goal)
        except PlanningConflict as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get('/projects/{project_id}/plan')
    def get_plan(project_id: UUID):
        project(project_id)
        return store.latest(project_id)

    @router.get('/projects/{project_id}/engineering-tasks')
    def get_tasks(project_id: UUID):
        project(project_id)
        return {'tasks': store.tasks(project_id)}

    @router.get('/projects/{project_id}/plans')
    def plan_history(project_id: UUID):
        project(project_id)
        return {'plans': store.history(project_id)}

    def plan(plan_id):
        found = store.get(plan_id)
        if found is None: raise HTTPException(404, 'Product plan not found.')
        return found

    @router.get('/product-plans/{plan_id}')
    def get_saved_plan(plan_id: UUID):
        return plan(plan_id)

    @router.put('/product-plans/{plan_id}/draft')
    def edit_draft(plan_id: UUID, body: DraftEdit, request: Request):
        origin(request)
        plan(plan_id)
        try: return store.edit(plan_id, body.draft, body.revision)
        except PlanningConflict as exc: raise HTTPException(409, str(exc)) from exc

    @router.post('/product-plans/{plan_id}/approve')
    def approve_plan(plan_id: UUID, body: PlanApproval, request: Request):
        origin(request)
        plan(plan_id)
        try: return store.approve(plan_id, body.revision)
        except PlanningConflict as exc: raise HTTPException(409, str(exc)) from exc

    @router.get('/engineering-tasks/{task_id}')
    def get_task(task_id: UUID):
        return task(task_id)

    @router.patch('/engineering-tasks/{task_id}/status')
    def change_status(task_id: UUID, body: StatusChange, request: Request):
        origin(request)
        task(task_id)
        try:
            return store.set_status(task_id, body.status, body.revision)
        except PlanningConflict as exc:
            raise HTTPException(409, str(exc)) from exc
    return router
