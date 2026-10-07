"""Durable task API; HTTP requests enqueue work and never own its lifetime."""
import asyncio
import json
from pathlib import Path
from typing import Literal
from uuid import UUID
import shutil

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import Field
from autonomous_engineering.domain.base import DomainModel
from autonomous_engineering.domain.tasks import TaskRequest, TaskRecord
from autonomous_engineering.workflows.state import WorkflowState
from autonomous_engineering.agents.developer import approval_identity, workspace_reader
from autonomous_engineering.tools.repository import RepositoryError, RepositoryReader
from autonomous_engineering.infrastructure.delivery import receipt, apply_original, export_commit
from autonomous_engineering.infrastructure.github import GitHub


class NewTask(DomainModel):
    repository_path: str = Field(min_length=1, max_length=4096)
    user_request: str = Field(min_length=1, max_length=20000)


class ApproveTask(DomainModel):
    approval_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    run_tests: bool = True
    test_backend: Literal['docker','local'] = 'docker'
    framework: Literal['unittest','pytest','npm'] = 'unittest'
    max_attempts: int = Field(default=3, ge=1, le=5)


class ProjectRequest(DomainModel):
    path: str
    name: str = Field(min_length=1,max_length=200)


class ImportRequest(DomainModel):
    repository: str = Field(min_length=1,max_length=300)
    branch: str | None = Field(default=None,max_length=200)


class DeliverRequest(DomainModel):
    receipt: str = Field(pattern=r'^[a-f0-9]{64}$')
    action: Literal['export','apply','github']


def task_router(config, store):
    router = APIRouter()
    def origin(request):
        value = request.headers.get('origin')
        if value is not None and value != str(request.base_url).rstrip('/'):
            raise HTTPException(403,'Requests must originate from this local workspace.')
    def get(task_id):
        result = store.get(task_id)
        if result is None:
            raise HTTPException(404,'Task not found.')
        return result
    def source(path):
        root = config.repository_root.resolve()
        target = Path(path).resolve() if Path(path).is_absolute() else (root / path).resolve()
        if not target.is_relative_to(root) or target.is_relative_to(config.workspace_root.resolve()):
            raise HTTPException(400,'Repository must be within ASE_REPOSITORY_ROOT and outside workspace storage.')
        try:
            RepositoryReader(target)
        except RepositoryError as exc:
            raise HTTPException(400,str(exc)) from exc
        return target

    @router.post('/tasks',status_code=202)
    def create(body: NewTask, request: Request):
        origin(request)
        target = source(body.repository_path)
        state = WorkflowState(task=TaskRecord(request=TaskRequest(repository_path=str(target),user_request=body.user_request)))
        options = {'run_tests':False,'framework':config.test_framework,'test_backend':config.test_backend,'max_attempts':3}
        project = store.register(str(target),{'name':target.name,'description':'Local repository','stack':[]})
        result = store.create(state,options)
        return {'id':result['id'],'phase':result['phase'],'snapshot':result['snapshot'],'project':project}

    @router.get('/tasks')
    def list_tasks(limit: int = 100):
        return {'tasks':store.list(max(1,min(limit,500)))}

    @router.get('/tasks/{task_id}')
    def task(task_id: UUID):
        return get(task_id)

    @router.get('/tasks/{task_id}/trace')
    def trace(task_id: UUID, after: int = 0):
        item = get(task_id)
        return {'events':store.trace(task_id,after),'executions':item['snapshot']['executions']}

    @router.get('/tasks/{task_id}/result')
    def result(task_id: UUID):
        item = get(task_id)
        if item['phase'] not in {'succeeded','failed','cancelled'}:
            raise HTTPException(409,'Task has not finished.')
        return item['snapshot']

    @router.post('/tasks/{task_id}/approve',status_code=202)
    def approve(task_id: UUID, body: ApproveTask, request: Request):
        origin(request)
        item = get(task_id)
        if body.test_backend == 'local' and body.framework == 'npm':
            raise HTTPException(400,'npm tests require a configured container runner image.')
        state = WorkflowState.model_validate(item['snapshot'])
        try:
            current = approval_identity(state,config.workspace_root)
        except RepositoryError as exc:
            raise HTTPException(409,str(exc)) from exc
        if current != body.approval_id or not store.approve(task_id,current,body.model_dump(exclude={'approval_id'})):
            raise HTTPException(409,'Approval is stale or already consumed; start a fresh task.')
        return {'id':str(task_id),'phase':'queued_development'}

    @router.post('/tasks/{task_id}/cancel',status_code=202)
    def cancel(task_id: UUID, request: Request):
        origin(request)
        get(task_id)
        if not store.cancel(task_id):
            raise HTTPException(409,'Task is already terminal.')
        return {'cancel_requested':True}

    @router.post('/tasks/{task_id}/retry',status_code=202)
    def retry(task_id: UUID, request: Request):
        origin(request)
        item = get(task_id)
        if item['phase'] not in {'failed','cancelled'}:
            raise HTTPException(409,'Only stopped tasks can be retried as a new run.')
        req = item['snapshot']['task']['request']
        return create(NewTask(**req),request)

    @router.get('/tasks/{task_id}/events')
    async def stream(task_id: UUID, request: Request, after: int = 0):
        get(task_id)
        try:
            after = max(after, int(request.headers.get('last-event-id', '0')))
        except ValueError:
            raise HTTPException(400, 'Invalid event cursor.')
        async def events():
            cursor = after
            while not await request.is_disconnected():
                rows = await asyncio.to_thread(store.trace,task_id,cursor)
                for row in rows:
                    cursor = row['id']
                    yield f"id: {cursor}\ndata: {json.dumps(row)}\n\n"
                item = await asyncio.to_thread(store.get,task_id)
                if item['phase'] in {'succeeded','failed','cancelled','awaiting_approval'}:
                    return
                if not rows:
                    yield ': keepalive\n\n'
                await asyncio.sleep(1)
        return StreamingResponse(events(),media_type='text/event-stream',headers={'Cache-Control':'no-store'})

    @router.get('/tasks/{task_id}/files')
    def files(task_id: UUID):
        state = WorkflowState.model_validate(get(task_id)['snapshot'])
        try:
            return {'run_id':str(state.run_id),'files':workspace_reader(state,config.workspace_root).inventory().files}
        except RepositoryError as exc:
            raise HTTPException(409,str(exc)) from exc

    @router.get('/tasks/{task_id}/file')
    def file(task_id: UUID, path: str):
        state = WorkflowState.model_validate(get(task_id)['snapshot'])
        try:
            content = workspace_reader(state,config.workspace_root).read_text(path)
            return JSONResponse({'path':path,'content':content},headers={'Cache-Control':'no-store'})
        except RepositoryError as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.get('/projects')
    def projects():
        return {'projects':store.projects()}

    @router.post('/projects',status_code=201)
    def project(body: ProjectRequest, request: Request):
        origin(request)
        target = source(body.path)
        return store.register(str(target),{'name':body.name,'description':'Local repository','stack':[]})

    @router.post('/projects/import',status_code=201)
    def import_project(body: ImportRequest, request: Request):
        origin(request)
        token = config.github_token.get_secret_value() if config.github_token else None
        try:
            target,data = GitHub(token).import_repository(body.repository,body.branch,config.repository_root)
            return store.register(str(target),data)
        except (RepositoryError, ValueError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.get('/tasks/{task_id}/delivery')
    def prepare_delivery(task_id: UUID):
        item = get(task_id)
        state = WorkflowState.model_validate(item['snapshot'])
        try:
            token = receipt(state,config.workspace_root)
        except RepositoryError as exc:
            raise HTTPException(409,str(exc)) from exc
        project = next((p for p in store.projects() if p['path']==state.task.request.repository_path),{})
        return {'receipt':token,'files':[c.path for c in state.changes],'diff':state.development.diff,
            'github_available':bool(config.github_token and project.get('github')),'github':project.get('github'), 'delivery':item['delivery']}

    @router.post('/tasks/{task_id}/delivery')
    def deliver(task_id: UUID, body: DeliverRequest, request: Request):
        origin(request)
        item = get(task_id)
        state = WorkflowState.model_validate(item['snapshot'])
        try:
            if body.receipt != receipt(state,config.workspace_root):
                raise RepositoryError('STALE_DELIVERY','Delivery receipt is stale.')
            previous = item['delivery']
            if previous.get(body.action):
                return previous[body.action]
            if previous.get('publishing') or not store.lock_delivery(task_id,previous):
                raise HTTPException(409,'A delivery operation is already active; inspect its state before retrying.')
            try:
                if body.action == 'export':
                    result = export_commit(state,config)
                elif body.action == 'apply':
                    result = apply_original(state,config)
                else:
                    project = next((p for p in store.projects() if p['path']==state.task.request.repository_path),{})
                    result = GitHub(config.github_token.get_secret_value() if config.github_token else None).publish(state,config,project)
                store.delivery(task_id,{**previous,body.action:result})
                return result
            except Exception:
                store.delivery(task_id,{**previous,'last_error':'Delivery failed; inspect local/remote artifacts before retrying.'})
                raise
        except RepositoryError as exc:
            raise HTTPException(409,str(exc)) from exc

    @router.get('/tasks/{task_id}/archive')
    def archive(task_id: UUID):
        item = get(task_id)
        exported = item['delivery'].get('export')
        if not exported:
            raise HTTPException(404,'Create a commit export first.')
        return FileResponse(exported['archive'],filename='engineering-'+str(task_id)+'.zip')

    @router.get('/system/status')
    def system():
        store.list(1)
        return {'database':store.engine.dialect.name,'model':config.ollama_model,'test_backend':config.test_backend,
            'active_workers':store.active_workers(config.lease_seconds*2),
            'github_configured':bool(config.github_token),'git_available':bool(shutil.which('git')),
            'docker_available':bool(shutil.which(config.docker_executable)), 'worker_command':'python -m autonomous_engineering.application.worker'}

    @router.get('/evaluation')
    def evaluation():
        from autonomous_engineering.application.evaluation import metrics
        return metrics(store.list(500))
    return router
