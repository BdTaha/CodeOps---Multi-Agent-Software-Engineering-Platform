"""Optional local development monitor, separate from the task-management API."""

import asyncio
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.background import BackgroundTask
from starlette.staticfiles import StaticFiles
from pydantic import Field

from autonomous_engineering.domain.base import DomainModel
from autonomous_engineering.agents.developer import approval_identity, workspace_reader
from autonomous_engineering.infrastructure.ollama_developer import OllamaDevelopmentProvider
from autonomous_engineering.infrastructure.test_process import LocalTestProcess
from autonomous_engineering.infrastructure.ollama_reviewer import OllamaReviewProvider
from autonomous_engineering.tools.repository import RepositoryError
from autonomous_engineering.workflows.development import develop_approved

from autonomous_engineering.core.config import Settings
from autonomous_engineering.domain.tasks import TaskRecord, TaskRequest
from autonomous_engineering.main import create_app
from autonomous_engineering.workflows.state import WorkflowState
from autonomous_engineering.workflows.streaming import stream_workflow


class ApprovalRequest(DomainModel):
    approval_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    run_tests: bool = False


def create_monitor_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else Settings()
    app = create_app(config)
    app.title = "Engineering Workflow Monitor"
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    run_lock = asyncio.Lock()
    pending: WorkflowState | None = None
    pending_id: str | None = None
    latest: WorkflowState | None = None
    activity: dict[str, str | None] = {"run_id": None, "node": None}

    frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend.is_dir():
        app.mount("/ui", StaticFiles(directory=frontend, html=True), name="frontend")

    def current_workspace(run_id: UUID):
        if latest is None or latest.run_id != run_id or latest.workspace_path is None:
            raise HTTPException(status_code=404, detail="This snapshot is no longer available in the local session.")
        try:
            return workspace_reader(latest, config.workspace_root)
        except RepositoryError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/monitor/workspace/{run_id}/files")
    async def workspace_files(run_id: UUID):
        reader = current_workspace(run_id)
        try:
            inventory = await asyncio.to_thread(reader.inventory)
            return {"run_id": str(run_id), "files": inventory.files}
        except RepositoryError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/monitor/workspace/{run_id}/file")
    async def workspace_file(run_id: UUID, path: str):
        reader = current_workspace(run_id)
        try:
            content = await asyncio.to_thread(reader.read_text, path)
            return JSONResponse({"path": path, "content": content}, headers={"Cache-Control": "no-store"})
        except RepositoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def check_origin(request: Request) -> None:
        origin = request.headers.get("origin")
        if origin is not None and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(status_code=403, detail="Requests must originate from this local monitor.")

    @app.get("/monitor/activity")
    async def current_activity():
        return JSONResponse(dict(activity), headers={"Cache-Control": "no-store"})

    @app.get("/monitor/approval")
    async def approval():
        if pending is None:
            return JSONResponse({"approval_id": None}, headers={"Cache-Control": "no-store"})
        return JSONResponse({"approval_id": pending_id, "run_id": str(pending.run_id),
            "plan": pending.plan.model_dump(mode="json")}, headers={"Cache-Control": "no-store"})

    @app.post("/monitor/develop")
    async def develop(body: ApprovalRequest, request: Request):
        nonlocal pending, pending_id, latest
        check_origin(request)
        if run_lock.locked():
            raise HTTPException(status_code=409, detail="A workflow is already running.")
        if pending is None or body.approval_id != pending_id:
            raise HTTPException(status_code=409, detail="Approval is stale or already used; run planning again.")
        if config.ollama_model is None:
            raise HTTPException(status_code=409, detail="Configure local Ollama before development.")
        await run_lock.acquire()
        snapshot = pending
        pending = None
        pending_id = None
        activity.update(run_id=str(snapshot.run_id), node="develop_implementation")
        try:
            job = asyncio.create_task(asyncio.to_thread(develop_approved, snapshot, config.workspace_root,
                body.approval_id, OllamaDevelopmentProvider(config),
                test_process=LocalTestProcess(config.test_timeout_seconds) if body.run_tests else None,
                review_provider=OllamaReviewProvider(config),
                on_node_started=lambda node: activity.update(node=node)))
            try:
                result = await asyncio.shield(job)
            except asyncio.CancelledError:
                # Do not release the shared lock while the writer still runs.
                await job
                raise
            latest = result
            return result
        finally:
            activity.update(run_id=None, node=None)
            run_lock.release()

    @app.get("/", include_in_schema=False)
    async def page() -> FileResponse:
        return FileResponse(Path(__file__).with_name("monitor.html"),
                            headers={"Cache-Control": "no-store"})

    @app.post("/monitor/run")
    async def run(task: TaskRequest, request: Request) -> StreamingResponse:
        nonlocal pending, pending_id, latest
        check_origin(request)
        if run_lock.locked():
            raise HTTPException(status_code=409, detail="A workflow is already running in this monitor.")
        await run_lock.acquire()
        pending = None
        pending_id = None
        latest = None
        released = False

        def release() -> None:
            nonlocal released
            if not released:
                released = True
                run_lock.release()

        async def events():
            nonlocal pending, pending_id, latest
            candidate = None
            completed = False
            try:
                initial = WorkflowState(task=TaskRecord(request=task))
                async for event in stream_workflow(initial, settings=config):
                    if event.snapshot is not None:
                        latest = event.snapshot
                    if event.kind == "node_completed" and event.node == "plan_implementation" and event.snapshot.plan is not None:
                        candidate = event.snapshot
                    if event.kind == "run_finished":
                        completed = True
                    yield f"data: {event.model_dump_json()}\n\n"
                if candidate is not None and completed:
                    try:
                        pending_id = await asyncio.to_thread(approval_identity, candidate, config.workspace_root)
                        pending = candidate
                    except RepositoryError:
                        pending_id = None
            finally:
                release()

        return StreamingResponse(events(), media_type="text/event-stream", background=BackgroundTask(release), headers={
            "Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no",
        })

    return app
