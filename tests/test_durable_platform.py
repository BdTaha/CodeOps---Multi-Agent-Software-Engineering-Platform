"""Real fixture workflows, durable leases, and explicit delivery boundaries."""
import os
from pathlib import Path
import shutil
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from test_developer import planned, FixtureDeveloper
from test_reviewer import FixtureReview
from test_test_execution import suite
from autonomous_engineering.agents.developer import approval_identity, DevelopmentProposal
from autonomous_engineering.core.config import Settings
from autonomous_engineering.domain.tasks import TaskStatus
from autonomous_engineering.infrastructure.task_store import TaskStore, tasks, LostLease
from autonomous_engineering.infrastructure.test_process import LocalTestProcess
from autonomous_engineering.infrastructure.docker_tests import DockerTestProcess
from autonomous_engineering.infrastructure.delivery import export_commit, apply_original, receipt
from autonomous_engineering.tools.repository import RepositoryError
from autonomous_engineering.workflows.development import develop_approved
from autonomous_engineering.workflows.state import WorkflowState, WorkflowUpdate
from autonomous_engineering.application.worker import Worker
from autonomous_engineering.platform import create_platform_app


def options():
    return dict(run_tests=True, test_backend='local', framework='unittest', max_attempts=3)


def queue_development(store, state, storage):
    item = store.create(state, options())
    owner = str(uuid4())
    assert store.claim(owner, 60)
    token = approval_identity(state, storage)
    store.checkpoint(item['id'], owner, state, phase='awaiting_approval', approval=token)
    assert store.approve(item['id'], token, options())
    assert not store.approve(item['id'], token, options())
    return item['id']


def test_database_reopens_and_leases_are_fenced(planned, tmp_path):
    state, storage, _ = planned
    url = 'sqlite:///' + str(tmp_path / 'tasks.db')
    store = TaskStore(url)
    item = store.create(state, options())
    assert store.claim('first', 60)
    assert store.claim('second', 60) is None
    with pytest.raises(LostLease):
        store.checkpoint(item['id'], 'second', state)
    store.close()
    reopened = TaskStore(url)
    assert reopened.get(item['id'])['snapshot']['run_id'] == str(state.run_id)
    assert len(reopened.trace(item['id'])) == 2
    with reopened.engine.begin() as db:
        db.execute(update(tasks).values(lease=time.time()-1))
    reopened.settle_interrupted()
    assert reopened.get(item['id'])['phase'] == 'failed'
    assert reopened.get(item['id'])['snapshot']['errors'][-1]['code'] == 'WORKER_INTERRUPTED'
    assert not reopened.heartbeat(item['id'], 'first', 60)
    reopened.close()


def test_cancellation_before_development_keeps_source(planned):
    state, storage, source = planned
    store = TaskStore('sqlite://')
    task_id = queue_development(store, state, storage)
    assert store.cancel(task_id)
    store.settle_interrupted()
    assert store.get(task_id)['phase'] == 'cancelled'
    assert source.joinpath('app.py').read_text().endswith('+ name\n')
    assert store.claim('worker', 60) is None


def test_bounded_repair_receives_failure_and_retains_original_diff(planned):
    state, storage, source = planned
    suite(Path(state.workspace_path), "        from app import greet\n        self.assertEqual(greet(' Ada '), 'Hello Ada')\n")
    class Repair:
        contexts = []
        def generate(self, context):
            self.contexts.append(context)
            content = "def greet(name):\n    return 'Wrong'\n" if context.attempt == 1 else "def greet(name):\n    return 'Hello ' + name.strip()\n"
            return DevelopmentProposal(explanation='Fixture repair', edits=[dict(path='app.py',kind='modified',content=content,summary='Fixture')])
    provider = Repair()
    result = develop_approved(state, storage, approval_identity(state,storage), provider,
        test_process=LocalTestProcess(), review_provider=FixtureReview(), allow_repairs=True)
    assert result.task.status == TaskStatus.SUCCEEDED
    assert result.development_attempts == 2
    assert provider.contexts[1].tests.outcome == 'failed'
    assert "-    return 'Hello ' + name" in result.development.diff
    assert "Wrong" not in result.development.diff
    assert result.development.original_files['app.py'] == source.joinpath('app.py').read_bytes().decode()


def test_worker_completes_independently_and_api_restores_history(planned):
    state, storage, source = planned
    suite(Path(state.workspace_path), "        from app import greet\n        self.assertEqual(greet(' Ada '), 'Hello Ada')\n")
    store = TaskStore('sqlite://')
    task_id = queue_development(store, state, storage)
    config = Settings(_env_file=None, workspace_root=storage, repository_root=source.parent)
    worker = Worker(config, store, FixtureDeveloper(), FixtureReview())
    assert worker.run_once()
    assert store.get(task_id)['phase'] == 'succeeded'
    with TestClient(create_platform_app(config,store)) as client:
        assert client.get('/tasks').json()['tasks'][0]['id'] == task_id
        assert client.get(f'/tasks/{task_id}/result').json()['task']['status'] == 'succeeded'
        assert client.get(f'/tasks/{task_id}/file',params={'path':'../secret'}).status_code == 400
        assert client.post(f'/tasks/{task_id}/retry').status_code == 409
        assert client.post('/tasks',json={'repository_path':str(source),'user_request':'Trim'},headers={'Origin':'https://evil.test'}).status_code == 403
        assert client.get('/system/status').json()['active_workers'] == 1


def test_export_is_real_git_and_apply_refuses_changed_source(planned, monkeypatch):
    state, storage, source = planned
    suite(Path(state.workspace_path), "        from app import greet\n        self.assertEqual(greet(' Ada '), 'Hello Ada')\n")
    result = develop_approved(state,storage,approval_identity(state,storage),FixtureDeveloper(edits=[dict(
        path='app.py',kind='modified',content="def greet(name):\n    return 'Hello ' + name.strip()\n",summary='Trim')]),
        test_process=LocalTestProcess(),review_provider=FixtureReview())
    git_directory = r'C:\Program Files\Git\cmd'
    if Path(git_directory).is_dir():
        monkeypatch.setenv('PATH',git_directory+os.pathsep+os.environ['PATH'])
    if not shutil.which('git'):
        pytest.skip('Git is required for actual export verification')
    config = Settings(_env_file=None, workspace_root=storage, repository_root=source.parent)
    exported = export_commit(result,config)
    assert len(exported['commit']) == 40 and Path(exported['archive']).is_file()
    assert Path(exported['export_path'], '.git').is_dir()
    source.joinpath('app.py').write_text('new user work\n')
    with pytest.raises(RepositoryError, match='changed'):
        apply_original(result,config)
    assert source.joinpath('app.py').read_text() == 'new user work\n'
    assert len(receipt(result,storage)) == 64


@pytest.mark.skipif(not os.environ.get('ASE_INTEGRATION_DOCKER'), reason='Explicit Docker integration opt-in')
@pytest.mark.parametrize('framework',['unittest','pytest'])
def test_real_offline_container_executes_tests(planned, framework):
    state, storage, _ = planned
    suite(Path(state.workspace_path), '        self.assertTrue(True)\n')
    config = Settings(_env_file=None, docker_executable=os.environ.get('ASE_DOCKER_EXECUTABLE','docker'))
    execution = DockerTestProcess(config, framework).run(Path(state.workspace_path))
    assert execution.exit_code == 0, execution.output_summary
    assert not execution.error
    assert '--network=none' in execution.command and '--read-only' in execution.command
    assert not Path(state.workspace_path,'__pycache__').exists()


@pytest.mark.skipif(not os.environ.get('ASE_INTEGRATION_DATABASE_URL'), reason='Explicit PostgreSQL integration opt-in')
def test_real_postgresql_claim_and_persistence(planned):
    state, _, _ = planned
    store = TaskStore(os.environ['ASE_INTEGRATION_DATABASE_URL'])
    item = store.create(state, options())
    assert store.claim(str(uuid4()),60)
    assert store.get(item['id'])['snapshot']['run_id'] == str(state.run_id)
    assert store.engine.dialect.name == 'postgresql'
    store.cancel(item['id']); store.settle_interrupted(); store.close()


@pytest.mark.skipif(not os.environ.get('ASE_INTEGRATION_DOCKER'), reason='Explicit Docker integration opt-in')
def test_container_network_user_and_readonly_source(planned):
    state, _, _ = planned
    suite(Path(state.workspace_path), """        import socket
        self.assertEqual(os.getuid(), 10001)
        with self.assertRaises(OSError):
            open('/source/app.py', 'w')
        with self.assertRaises(OSError):
            open('/etc/ase-test-file', 'w')
        with socket.socket() as connection:
            connection.settimeout(1)
            with self.assertRaises(OSError):
                connection.connect(('1.1.1.1', 80))
""")
    config = Settings(_env_file=None,docker_executable=os.environ.get('ASE_DOCKER_EXECUTABLE','docker'))
    execution = DockerTestProcess(config).run(Path(state.workspace_path))
    assert execution.exit_code == 0, execution.output_summary


@pytest.mark.skipif(not os.environ.get('ASE_INTEGRATION_DOCKER'), reason='Explicit Docker integration opt-in')
def test_container_timeout_is_recorded_and_bounded(planned):
    state, _, _ = planned
    suite(Path(state.workspace_path), '        time.sleep(30)\n')
    config = Settings(_env_file=None,test_timeout_seconds=1,docker_executable=os.environ.get('ASE_DOCKER_EXECUTABLE','docker'))
    execution = DockerTestProcess(config).run(Path(state.workspace_path))
    assert execution.timed_out and execution.duration_seconds < 15


@pytest.mark.skipif(not os.environ.get('ASE_NODE_DOCKER_IMAGE'), reason='Explicit Node runner integration opt-in')
def test_real_npm_runner(planned):
    state, _, _ = planned
    root = Path(state.workspace_path)
    root.joinpath('package.json').write_text('{"scripts":{"test":"node check.cjs"}}')
    root.joinpath('check.cjs').write_text("require('node:assert/strict').equal(2+2, 4); console.log('Actual Node test passed');")
    config = Settings(_env_file=None,docker_image=os.environ['ASE_NODE_DOCKER_IMAGE'],docker_executable=os.environ.get('ASE_DOCKER_EXECUTABLE','docker'))
    execution = DockerTestProcess(config,'npm').run(root)
    assert execution.exit_code == 0, execution.output_summary
    assert 'Actual Node test passed' in execution.output_summary


def test_failed_validation_stops_at_attempt_budget(planned):
    state, storage, _ = planned
    suite(Path(state.workspace_path),'        self.fail("Fixture remains failing")\n')
    class AlwaysFail:
        def generate(self, context):
            return DevelopmentProposal(explanation='Fixture', edits=[dict(path='app.py',kind='modified',
                content=f'fixture_attempt = {context.attempt}\n',summary='Fixture')])
    result = develop_approved(state,storage,approval_identity(state,storage),AlwaysFail(),
        test_process=LocalTestProcess(),review_provider=FixtureReview(),allow_repairs=True)
    assert result.task.status == 'failed'
    assert result.development_attempts == result.max_development_attempts
    assert result.review is None
