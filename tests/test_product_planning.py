"""Product planning contracts, durable jobs and manually managed board tasks."""
import copy
import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, update

from autonomous_engineering.agents.planner import PlanningError
from autonomous_engineering.agents.product_planner import ProductPlanningAgent
from autonomous_engineering.application.worker import Worker
from autonomous_engineering.core.config import Settings
from autonomous_engineering.domain.product_planning import EngineeringStatus, ProductPlanDraft
from autonomous_engineering.infrastructure.ollama_product import OllamaProductPlanProvider
from autonomous_engineering.infrastructure.planning_store import PlanningConflict, PlanningStore, goals, engineering_tasks
from autonomous_engineering.infrastructure.task_store import LostLease, TaskStore
from autonomous_engineering.platform import create_platform_app
from test_planner import ollama_server


def draft_data():
    # Explicit fixture data is never used by the real provider or frontend.
    return dict(title='Fixture authentication', summary='Fixture goal breakdown', assumptions=['Existing API is available'],
        epics=[dict(ref='E1', title='Core authentication', description='Fixture epic')], tasks=[
            dict(ref='T1', epic_ref='E1', title='User model', description='Store users securely', priority='high',
                estimated_hours=2, technical_area='Database', dependencies=[], acceptance_criteria=[dict(description='Email is unique')]),
            dict(ref='T2', epic_ref='E1', title='Registration', description='Register a user', priority='high',
                estimated_hours=4, technical_area='Backend', dependencies=['T1'], acceptance_criteria=[dict(description='Duplicate email is rejected')]),
        ])


class Provider:
    model = 'explicit-test-fixture'
    def __init__(self, responses=None):
        self.contexts = []
        self.responses = responses
    def generate(self, context):
        self.contexts.append(context)
        return self.responses[len(self.contexts)-1] if self.responses else draft_data()


@pytest.fixture
def product(tmp_path):
    config = Settings(_env_file=None, environment='test', repository_root=tmp_path, workspace_root=tmp_path/'workspaces')
    source = tmp_path/'source'
    source.mkdir()
    source.joinpath('app.py').write_text('value = 1\n')
    store = TaskStore('sqlite:///' + str(tmp_path/'planning.db'))
    project = store.register(str(source), dict(name='Fixture project', description='Local fixture', stack=['Python']))
    planning = PlanningStore(store.engine)
    yield config, store, planning, project
    store.close()


@pytest.mark.parametrize('issue', ['duplicate_task', 'duplicate_epic', 'unknown_epic', 'empty_epic', 'unknown_dependency',
    'self_dependency', 'cycle', 'duplicate_dependency', 'no_criteria', 'missing_estimate', 'negative_estimate', 'oversized_task', 'infinite_estimate', 'extra_field'])
def test_plan_validates_graph_and_required_fields(issue):
    data = draft_data()
    if issue == 'duplicate_task': data['tasks'][1]['ref'] = 'T1'
    if issue == 'duplicate_epic': data['epics'].append(copy.deepcopy(data['epics'][0]))
    if issue == 'unknown_epic': data['tasks'][0]['epic_ref'] = 'E8'
    if issue == 'empty_epic': data['epics'].append(dict(ref='E2', title='Empty', description='No tasks'))
    if issue == 'unknown_dependency': data['tasks'][1]['dependencies'] = ['T8']
    if issue == 'self_dependency': data['tasks'][0]['dependencies'] = ['T1']
    if issue == 'cycle': data['tasks'][0]['dependencies'] = ['T2']
    if issue == 'duplicate_dependency': data['tasks'][1]['dependencies'] = ['T1', 'T1']
    if issue == 'no_criteria': data['tasks'][0]['acceptance_criteria'] = []
    if issue == 'missing_estimate': del data['tasks'][0]['estimated_hours']
    if issue == 'negative_estimate': data['tasks'][0]['estimated_hours'] = -2
    if issue == 'oversized_task': data['tasks'][0]['estimated_hours'] = 25
    if issue == 'infinite_estimate': data['tasks'][0]['estimated_hours'] = float('inf')
    if issue == 'extra_field': data['tasks'][0]['assigned_user'] = 'invented'
    with pytest.raises(ValidationError): ProductPlanDraft.model_validate(data)


def test_agent_retries_invalid_output_once_without_inventing_fields():
    invalid = draft_data()
    del invalid['tasks'][0]['estimated_hours']
    provider = Provider([invalid, draft_data()])
    result = ProductPlanningAgent(provider).plan('Authentication', dict(name='Demo', path='secret-local-path'))
    assert result.tasks[0].estimated_hours == 2
    assert len(provider.contexts) == 2
    assert 'estimated_hours' in provider.contexts[1].validation_feedback
    assert 'secret-local-path' not in provider.contexts[0].model_dump_json()
    broken = Provider([invalid, invalid])
    with pytest.raises(PlanningError) as error:
        ProductPlanningAgent(broken).plan('Authentication', dict(name='Demo'))
    assert error.value.code == 'INVALID_PRODUCT_PLAN'
    assert len(broken.contexts) == 2


def test_ollama_product_provider_uses_existing_local_structured_transport(ollama_server):
    url, behavior, captured = ollama_server
    behavior['body'] = {'done': True, 'message': {'content': json.dumps(draft_data())}}
    provider = OllamaProductPlanProvider(Settings(_env_file=None, ollama_base_url=url, ollama_model='fixture-model'))
    plan = ProductPlanningAgent(provider).plan('Authentication', dict(name='Demo'))
    assert len(plan.tasks) == 2
    body = captured[0][1]
    assert body['format'] == ProductPlanDraft.model_json_schema()
    assert body['model'] == 'fixture-model'
    assert json.loads(body['messages'][1]['content'])['task'] == {'user_request': 'Authentication'}


def test_ollama_invalid_graph_returns_specific_feedback_on_bounded_retry(ollama_server):
    url, behavior, captured = ollama_server
    data = draft_data()
    data['tasks'][0]['dependencies'] = ['T2']
    behavior['body'] = {'done': True, 'message': {'content': json.dumps(data)}}
    provider = OllamaProductPlanProvider(Settings(_env_file=None, ollama_base_url=url, ollama_model='fixture-model'))
    with pytest.raises(PlanningError) as error:
        ProductPlanningAgent(provider).plan('Authentication', dict(name='Demo'))
    assert error.value.code == 'INVALID_PRODUCT_PLAN'
    assert len(captured) == 2
    assert 'cycles' in json.loads(captured[1][1]['messages'][1]['content'])['validation_feedback']


def test_worker_api_and_status_survive_database_reopen(product):
    config, store, planning, project = product
    with TestClient(create_platform_app(config, store)) as client:
        assert client.get(f"/projects/{project['id']}/plan").json() is None
        result = client.post(f"/projects/{project['id']}/plans", json={'goal': 'Build authentication'})
        assert result.status_code == 202
        assert result.json()['status'] == 'queued' and result.json()['plan'] is None
        assert client.post(f"/projects/{project['id']}/plans", json={'goal': 'Second simultaneous goal'}).status_code == 409
        assert store.list() == []  # Product goals do not create execution tasks.
        provider = Provider()
        worker = Worker(config, store, product_plan_provider=provider)
        assert worker.run_once()
        saved = client.get(f"/projects/{project['id']}/plan").json()
        assert saved['status'] == 'ready'
        assert saved['plan']['estimated_hours'] == 6
        assert 'not guaranteed' in saved['plan']['estimate_notice']
        tasks = saved['plan']['tasks']
        assert [task['key'] for task in tasks] == ['CO-1', 'CO-2']
        assert tasks[1]['dependencies'] == [{'task_id': tasks[0]['id']}]
        assert all(task['execution_run_id'] is None and task['status'] == 'backlog' for task in tasks)
        first = tasks[0]
        for status in ['planned', 'in_progress', 'review', 'done']:
            moved = client.patch(f"/engineering-tasks/{first['id']}/status", json={'status': status, 'revision': first['revision']})
            assert moved.status_code == 200
            first = moved.json()
            assert first['status'] == status
        assert client.patch(f"/engineering-tasks/{first['id']}/status", json={'status':'backlog', 'revision':0}).status_code == 409
        assert client.get(f"/engineering-tasks/{first['id']}").json() == first
        assert len(client.get(f"/projects/{project['id']}/engineering-tasks").json()['tasks']) == 2
        assert store.list() == []
        assert not worker.run_once()
    # A new store represents a new API process after a browser/server restart.
    reopened = TaskStore(str(store.engine.url))
    try:
        restored = PlanningStore(reopened.engine).latest(project['id'])
        assert restored.plan.tasks[0].status == EngineeringStatus.DONE
        assert restored.plan.tasks[0].revision == 4
        assert len(restored.plan.epics) == 1
    finally: reopened.close()


def test_invalid_generation_persists_failure_without_partial_tasks(product):
    config, store, planning, project = product
    invalid = draft_data()
    invalid['tasks'][0]['dependencies'] = ['T2']
    planning.enqueue(project['id'], 'Authentication')
    provider = Provider([invalid, invalid])
    assert Worker(config, store, product_plan_provider=provider).run_once()
    record = planning.latest(project['id'])
    assert record.status == 'failed' and record.plan is None and record.attempts == 2
    assert 'INVALID_PRODUCT_PLAN' in record.error
    with store.engine.connect() as db:
        assert not db.execute(select(engineering_tasks)).first()
    assert planning.enqueue(project['id'], 'Retry authentication').status == 'queued'


def test_plan_leases_fence_completion_and_recover_interruption(product):
    config, store, planning, project = product
    record = planning.enqueue(project['id'], 'Authentication')
    job = planning.claim('first', 60)
    assert job and planning.claim('other', 60) is None
    assert not planning.heartbeat(str(record.goal.id), 'other', 60)
    with pytest.raises(LostLease): planning.complete(job['id'], 'other', ProductPlanDraft.model_validate(draft_data()), 1, 'fixture')
    with store.engine.begin() as db: db.execute(update(goals).values(lease=time.time()-1))
    planning.settle_interrupted()
    assert planning.latest(project['id']).status == 'failed'
    with pytest.raises(LostLease): planning.complete(job['id'], 'first', ProductPlanDraft.model_validate(draft_data()), 1, 'fixture')
    assert planning.latest(project['id']).plan is None


def test_new_plan_keeps_previous_tasks_and_increments_project_keys(product):
    config, store, planning, project = product
    first = planning.enqueue(project['id'], 'First goal')
    worker = Worker(config, store, product_plan_provider=Provider())
    worker.run_once()
    old = planning.latest(project['id']).plan
    planning.set_status(old.tasks[0].id, EngineeringStatus.DONE, 0)
    planning.enqueue(project['id'], 'Second goal')
    worker.run_once()
    latest = planning.latest(project['id']).plan
    assert [task.key for task in latest.tasks] == ['CO-3', 'CO-4']
    assert planning.get(first.goal.id).plan.tasks[0].status == EngineeringStatus.DONE
    assert planning.task(old.tasks[0].id).status == EngineeringStatus.DONE


def test_planning_routes_reject_unknown_projects_and_cross_origin_writes(product):
    config, store, planning, project = product
    with TestClient(create_platform_app(config, store)) as client:
        assert client.get(f'/projects/{uuid4()}/plan').status_code == 404
        assert client.get(f'/engineering-tasks/{uuid4()}').status_code == 404
        route = f"/projects/{project['id']}/plans"
        assert client.post(route, json={'goal':'Authentication'}, headers={'Origin':'https://elsewhere.test'}).status_code == 403
        assert client.post(route, json={'goal':'  '}).status_code == 422
        assert client.post(route, json={'goal':'Authentication', 'execute':True}).status_code == 422
        planning.enqueue(project['id'], 'Authentication')
        Worker(config, store, product_plan_provider=Provider()).run_once()
        task = planning.latest(project['id']).plan.tasks[0]
        assert client.patch(f'/engineering-tasks/{task.id}/status', json={'status':'invented', 'revision':0}).status_code == 422
        assert client.patch(f'/engineering-tasks/{task.id}/status', json={'status':'done', 'revision':0}, headers={'Origin':'https://elsewhere.test'}).status_code == 403
        assert planning.task(task.id).status == EngineeringStatus.BACKLOG
