"""Local preview configuration and durable requests; no long-running API builds."""
from uuid import UUID
import json
from fastapi import APIRouter, HTTPException, Request
from autonomous_engineering.domain.previews import PreviewProfileInput
from autonomous_engineering.domain.task_executions import ReviewExecution
from autonomous_engineering.infrastructure.planning_store import PlanningConflict
from autonomous_engineering.infrastructure.team_store import TeamNotFound
from autonomous_engineering.tools.repository import RepositoryError

def preview_router(store):
    router=APIRouter(tags=['Local previews'])
    async def unique_keys(request):
        def pairs(items):
            result={}
            for key,value in items:
                if key in result: raise ValueError('Duplicate JSON/environment keys are not allowed.')
                result[key]=value
            return result
        try: json.loads(await request.body(),object_pairs_hook=pairs)
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    def call(action,request=None):
        if request and request.headers.get('origin') not in {None,str(request.base_url).rstrip('/')}:
            raise HTTPException(403,'Requests must originate from this local workspace.')
        try: return action()
        except TeamNotFound as exc: raise HTTPException(404,str(exc)) from exc
        except (PlanningConflict,RepositoryError) as exc: raise HTTPException(409,str(exc)) from exc
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    @router.get('/projects/{project_id}/preview-profile')
    def profile(project_id:UUID): return call(lambda:store.profile(project_id))
    @router.put('/projects/{project_id}/preview-profile')
    async def save(project_id:UUID,body:PreviewProfileInput,request:Request):
        await unique_keys(request)
        return call(lambda:store.save_profile(project_id,body),request)
    @router.post('/projects/{project_id}/preview-profile/validate')
    async def validate(project_id:UUID,body:PreviewProfileInput,request:Request):
        await unique_keys(request)
        call(lambda:store.profile(project_id),request)
        return dict(valid=True,runnable=body.enabled and body.preview_type!='none' and not body.requires_external_services,
            message='Schema validated only. No commands ran. External services are unsupported.' if body.requires_external_services else 'Schema validated only. Start Preview on a successful pending-review run to test startup.')
    @router.get('/engineering-tasks/{task_id}/preview')
    def current(task_id:UUID,details:bool=True):
        result=call(lambda:store.snapshot(task_id))
        if not details:
            result['history']=[{**preview,'logs':''} for preview in result['history']]
            if result['current']: result['current']={**result['current'],'logs':''}
        return result
    @router.post('/engineering-tasks/{task_id}/preview',status_code=202)
    def start(task_id:UUID,body:ReviewExecution,request:Request): return call(lambda:store.start(task_id,body.revision,body.execution_task_id),request)
    @router.post('/previews/{preview_id}/stop',status_code=202)
    def stop(preview_id:UUID,request:Request): return call(lambda:store.stop(preview_id),request)
    @router.post('/previews/{preview_id}/restart',status_code=202)
    def restart(preview_id:UUID,body:ReviewExecution,request:Request): return call(lambda:store.restart(preview_id,body.revision,body.execution_task_id),request)
    @router.get('/previews/{preview_id}/logs')
    def logs(preview_id:UUID):
        result=call(lambda:store.get(preview_id))
        return dict(id=result['id'],status=result['status'],logs=result['logs'],failure_reason=result['failure_reason'])
    return router
