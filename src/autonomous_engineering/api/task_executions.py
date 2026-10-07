"""Small bridge API; existing approval, cancellation, trace and delivery APIs remain."""
from uuid import UUID
from fastapi import APIRouter, HTTPException, Request
from autonomous_engineering.domain.task_executions import StartExecution, ReviewExecution, RequestChanges
from autonomous_engineering.infrastructure.planning_store import PlanningConflict
from autonomous_engineering.infrastructure.team_store import TeamNotFound
from autonomous_engineering.tools.repository import RepositoryError


def task_execution_router(store):
    router = APIRouter(tags=['Engineering task executions'])
    def origin(request):
        if request.headers.get('origin') not in {None,str(request.base_url).rstrip('/')}:
            raise HTTPException(403,'Requests must originate from this local workspace.')
    def call(action):
        try: return action()
        except TeamNotFound as exc: raise HTTPException(404,str(exc)) from exc
        except (PlanningConflict, RepositoryError) as exc: raise HTTPException(409,str(exc)) from exc
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc

    @router.get('/engineering-tasks/{task_id}/execution')
    def current(task_id: UUID):
        return call(lambda:store.snapshot(task_id))

    @router.get('/engineering-tasks/{task_id}/executions')
    def history(task_id: UUID):
        return {'executions':call(lambda:store.snapshot(task_id))['history']}

    @router.post('/engineering-tasks/{task_id}/executions',status_code=202)
    def start(task_id: UUID, body: StartExecution, request: Request):
        origin(request)
        return call(lambda:store.start(task_id,body.revision))

    @router.post('/engineering-tasks/{task_id}/accept')
    def accept(task_id: UUID, body: ReviewExecution, request: Request):
        origin(request)
        return call(lambda:store.accept(task_id,body.revision,body.execution_task_id))

    @router.post('/engineering-tasks/{task_id}/request-changes',status_code=202)
    def changes(task_id: UUID, body: RequestChanges, request: Request):
        origin(request)
        return call(lambda:store.start(task_id,body.revision,body.feedback,body.execution_task_id))
    return router
