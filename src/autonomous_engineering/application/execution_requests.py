"""Shared entry boundary for the existing autonomous execution workflow."""
from pathlib import Path
from autonomous_engineering.domain.tasks import TaskRecord, TaskRequest
from autonomous_engineering.workflows.state import WorkflowState
from autonomous_engineering.tools.repository import RepositoryReader, RepositoryError


def repository_source(config, path):
    root = config.repository_root.resolve()
    target = Path(path).resolve() if Path(path).is_absolute() else (root / path).resolve()
    if not target.is_relative_to(root) or target.is_relative_to(config.workspace_root.resolve()):
        raise RepositoryError('INVALID_REPOSITORY', 'Repository must be within ASE_REPOSITORY_ROOT and outside workspace storage.')
    RepositoryReader(target)
    return target


def execution_request(config, path, request):
    target = repository_source(config, path)
    state = WorkflowState(task=TaskRecord(request=TaskRequest(repository_path=str(target), user_request=request)))
    options = dict(run_tests=False, framework=config.test_framework, test_backend=config.test_backend, max_attempts=3)
    return state, options
