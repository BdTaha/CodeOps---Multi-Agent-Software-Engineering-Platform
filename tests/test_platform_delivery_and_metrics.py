"""GitHub adapter contracts and honest evaluation telemetry, without publishing."""
from pathlib import Path
import pytest
from test_developer import planned, FixtureDeveloper
from test_reviewer import FixtureReview
from test_test_execution import suite
from autonomous_engineering.agents.developer import approval_identity
from autonomous_engineering.application.evaluation import metrics
from autonomous_engineering.core.config import Settings
from autonomous_engineering.infrastructure.github import GitHub
from autonomous_engineering.infrastructure.test_process import LocalTestProcess
from autonomous_engineering.infrastructure.task_store import TaskStore, tasks
from autonomous_engineering.tools.repository import RepositoryError
from autonomous_engineering.workflows.development import develop_approved
from sqlalchemy import update
import time


def successful(planned):
    state, storage, source = planned
    suite(Path(state.workspace_path), "        from app import greet\n        self.assertEqual(greet(' Ada '), 'Hello Ada')\n")
    result = develop_approved(state,storage,approval_identity(state,storage),FixtureDeveloper(),
        test_process=LocalTestProcess(),review_provider=FixtureReview())
    return result, Settings(_env_file=None, workspace_root=storage, repository_root=source.parent)


def test_git_api_preserves_base_tree_and_creates_draft(planned):
    state, config = successful(planned)
    class MockGitHub(GitHub):
        calls=[]
        def call(self, method, path, body=None):
            self.calls.append((method,path,body))
            if '/commits/' in path:
                return {'sha':'baseline','commit':{'tree':{'sha':'complete-base-tree'}}}
            if '/git/ref/' in path:
                raise RepositoryError('GITHUB_FAILED','HTTP 404')
            if method == 'GET' and '/pulls?' in path:
                return []
            if method == 'POST' and path.endswith('/pulls'):
                return {'html_url':'https://github.com/example/repo/pull/1'}
            return {'sha':'new-object'}
    github = MockGitHub('fixture-token')
    project = {'github':{'slug':'example/repo','base':'main','base_sha':'baseline'}}
    result = github.publish(state,config,project)
    assert result['url'].endswith('/pull/1')
    tree = next(body for _,path,body in github.calls if path.endswith('/git/trees'))
    assert tree['base_tree'] == 'complete-base-tree'
    assert next(c for c in tree['tree'] if c['path']=='old.py')['sha'] is None
    pr = next(body for _,path,body in github.calls if path.endswith('/pulls'))
    assert pr['draft'] is True
    assert 'fixture-token' not in str(github.calls)


def test_github_moved_base_refuses_all_mutations(planned):
    state, config = successful(planned)
    class Moved(GitHub):
        def call(self, method,path,body=None):
            assert method == 'GET'
            return {'sha':'different'}
    with pytest.raises(RepositoryError,match='moved'):
        Moved('fixture-token').publish(state,config,{'github':{'slug':'a/b','base':'main','base_sha':'old'}})


def test_empty_metrics_keep_unknowns_unknown():
    result = metrics([])
    assert result['task_success_rate'] is None
    assert result['input_tokens_observed'] is None
    assert result['llm_cost'] is None


def test_terminal_checkpoint_survives_expired_lease(planned):
    state, config = successful(planned)
    store = TaskStore('sqlite://')
    task_id = store.create(state,dict(run_tests=True))['id']
    store.claim('worker',60)
    with store.engine.begin() as db:
        db.execute(update(tasks).where(tasks.c.id==task_id).values(lease=time.time()-1))
    store.settle_interrupted()
    assert store.get(task_id)['phase'] == 'succeeded'
    assert store.get(task_id)['snapshot']['task']['status'] == 'succeeded'
