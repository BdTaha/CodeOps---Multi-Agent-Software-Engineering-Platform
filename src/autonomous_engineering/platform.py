"""Durable local platform factory. Run workers as separate processes."""
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi.responses import RedirectResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles
from autonomous_engineering.core.config import Settings
from autonomous_engineering.main import create_app
from autonomous_engineering.api.tasks import task_router
from autonomous_engineering.infrastructure.task_store import TaskStore
from autonomous_engineering.infrastructure.planning_store import PlanningStore
from autonomous_engineering.api.planning import planning_router
from autonomous_engineering.api.teams import team_router
from autonomous_engineering.infrastructure.team_store import TeamStore


def create_platform_app(settings=None, store=None):
    config = settings or Settings()
    app = create_app(config)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['localhost','127.0.0.1','testserver'])
    app.state.task_store = store or TaskStore(config.database_url.get_secret_value())
    original_lifespan = app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        try:
            async with original_lifespan(application):
                yield
        finally:
            if store is None:
                application.state.task_store.close()
    app.router.lifespan_context = lifespan
    app.include_router(task_router(config,app.state.task_store))
    app.state.planning_store = PlanningStore(app.state.task_store.engine)
    app.include_router(planning_router(app.state.planning_store))
    app.state.team_store = TeamStore(app.state.planning_store)
    app.include_router(team_router(app.state.team_store))
    from autonomous_engineering.infrastructure.task_execution_store import TaskExecutionStore
    from autonomous_engineering.api.task_executions import task_execution_router
    app.state.task_execution_store = TaskExecutionStore(config, app.state.task_store, app.state.team_store)
    app.include_router(task_execution_router(app.state.task_execution_store))
    frontend = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
    if frontend.is_dir():
        app.mount('/ui',StaticFiles(directory=frontend,html=True),name='frontend')
    @app.get('/',include_in_schema=False)
    def root():
        return RedirectResponse('/ui/')
    return app
