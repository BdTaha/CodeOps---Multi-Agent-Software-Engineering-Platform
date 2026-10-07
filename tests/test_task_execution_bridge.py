"""Real existing worker/approval/development flow and relational bridge races."""
import os
import time
from uuid import uuid4
from pathlib import Path
from threading import Barrier
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.engine import make_url
from autonomous_engineering.core.config import Settings
from autonomous_engineering.domain.product_planning import ProductPlanDraft, EngineeringStatus
from autonomous_engineering.domain.tasks import TaskStatus
from autonomous_engineering.domain.execution import ExecutionError
from autonomous_engineering.domain.results import ImplementationPlan, ReportSummary
from autonomous_engineering.infrastructure.task_store import TaskStore, tasks, events
from autonomous_engineering.infrastructure.planning_store import PlanningStore
from autonomous_engineering.infrastructure.team_store import TeamStore
from autonomous_engineering.infrastructure.task_execution_tables import execution_links
from autonomous_engineering.application.worker import Worker
from autonomous_engineering.workflows.state import WorkflowState, WorkflowUpdate
from autonomous_engineering.platform import create_platform_app
from test_developer import FixtureDeveloper
from test_reviewer import FixtureReview
from test_workspace_resources import resource, join, edit_resource


class BridgePlanner:
    def __init__(self): self.context = None
    def generate(self, context):
        self.context = context
        return ImplementationPlan(problem_interpretation='Explicit fixture: trim greeting names',
            steps=[dict(description='Trim greeting input while preserving Hello',files=['app.py'])],
            tests_to_run=['Run existing greeting unittest'])


@pytest.fixture(params=['sqlite','postgresql'])
def bridge(request,tmp_path):
    url = 'sqlite:///'+str(tmp_path/'bridge.db')
    root_engine = None; schema = None
    if request.param=='postgresql':
        if not os.environ.get('ASE_INTEGRATION_DATABASE_URL'): pytest.skip('Explicit PostgreSQL integration opt-in')
        schema = 'bridge_'+uuid4().hex
        root_engine = create_engine(os.environ['ASE_INTEGRATION_DATABASE_URL'])
        with root_engine.begin() as db: db.exec_driver_sql(f'CREATE SCHEMA {schema}')
        url = make_url(os.environ['ASE_INTEGRATION_DATABASE_URL']).update_query_dict({'options':'-csearch_path='+schema}).render_as_string(hide_password=False)
    store = TaskStore(url); planning = PlanningStore(store.engine); projects=[]
    for index in range(2):
        source=tmp_path/('repository-'+str(index));source.mkdir()
        (source/'app.py').write_text("def greet(name):\n    return 'Hello ' + name\n",encoding='utf-8')
        (source/'tests').mkdir()
        (source/'tests'/'test_app.py').write_text("import unittest\nfrom app import greet\nclass Greeting(unittest.TestCase):\n    def test_trim(self):\n        self.assertEqual(greet(' Ada '), 'Hello Ada')\n",encoding='utf-8')
        project=store.register(str(source),dict(name='Bridge fixture '+str(index),description='',stack=['Python']))
        goal=planning.enqueue(project['id'],'Explicit test product plan'); job=planning.claim('fixture',60)
        draft=ProductPlanDraft.model_validate(dict(title='Fixture plan',summary='Explicit test requirements',assumptions=[],
            epics=[dict(ref='E1',title='Greetings',description='Fixture epic')],tasks=[
                dict(ref='T'+str(n+1),epic_ref='E1',title='Trim greeting '+str(n),description='Trim surrounding whitespace in greet(name)',
                    priority='high',estimated_hours=2,technical_area='Backend',dependencies=[],
                    acceptance_criteria=[dict(description='Leading and trailing whitespace is ignored')]) for n in range(2)]))
        planning.complete(str(goal.goal.id),'fixture',draft,1,'fixture'); projects.append(project)
    config=Settings(_env_file=None,environment='test',repository_root=tmp_path,workspace_root=tmp_path/'snapshots',test_backend='local')
    app=create_platform_app(config,store)
    with TestClient(app) as client:
        ai=resource(client,ai=True,name='Bridge AI')
        joins=[join(client,project,ai) for project in projects]
        for project in projects:
            for task in planning.latest(project['id']).plan.tasks:
                result=client.post(f'/engineering-tasks/{task.id}/assignment',json=dict(assignee_id=ai['id'],revision=task.revision))
                assert result.status_code==200,result.text
        yield client,app,store,planning,projects,ai,joins,config
    store.close()
    if root_engine:
        with root_engine.begin() as db: db.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
        root_engine.dispose()


def first(bridge,index=0):
    return bridge[3].latest(bridge[4][index]['id']).plan.tasks[0]


def start(bridge,task=None):
    client=bridge[0];task=task or first(bridge)
    return client.post(f'/engineering-tasks/{task.id}/executions',json=dict(revision=task.revision))


def worker_for(bridge,developer=None):
    planner=BridgePlanner()
    developer=developer or FixtureDeveloper(edits=[dict(path='app.py',kind='modified',content="def greet(name):\n    return 'Hello ' + name.strip()\n",summary='Trim names')])
    return Worker(bridge[7],bridge[2],developer,FixtureReview(),coding_plan_provider=planner),planner,developer


def success(bridge):
    result=start(bridge);assert result.status_code==202,result.text
    record=result.json();job_id=record['execution']['id'];worker,planner,developer=worker_for(bridge)
    assert worker.run_once()
    job=bridge[2].get(job_id)
    assert job['phase']=='awaiting_approval' and not developer.called
    capacity=bridge[0].get(f"/workspace/members/{bridge[5]['id']}/capacity").json()
    assert capacity['active_execution_count']==1 and capacity['assigned_queue_depth']==4
    assert Path(job['snapshot']['workspace_path'],'app.py').read_text().endswith('+ name\n')
    assert bridge[0].post(f'/tasks/{job_id}/approve',json=dict(approval_id=job['approval'],run_tests=True,test_backend='local',framework='unittest',max_attempts=1)).status_code==202
    assert worker.run_once()
    assert bridge[2].get(job_id)['phase']=='succeeded'
    return bridge[0].get(f'/engineering-tasks/{first(bridge).id}/execution').json(),worker,planner,developer


def test_request_approval_real_worker_review_acceptance_and_delivery_boundary(bridge):
    client,app,store,planning,projects,ai,joins,config=bridge
    result,worker,planner,developer=success(bridge)
    task=result['task'];job=result['execution'];snapshot=job['snapshot']
    assert task['status']=='review' and task['execution_run_id']==snapshot['run_id']
    assert store.get(job['id'])['engineering_origin']['engineering_task_id']==task['id']
    request=planner.context.task.user_request
    assert task['key'] in request and 'Leading and trailing whitespace is ignored' in request and projects[0]['path'] in request
    assert Path(snapshot['workspace_path']) != Path(projects[0]['path'])
    assert Path(projects[0]['path'],'app.py').read_text().endswith('+ name\n')
    assert snapshot['tests']['outcome']=='passed' and snapshot['review']['approved']
    assert client.patch(f"/engineering-tasks/{task['id']}/status",json=dict(status='done',revision=task['revision'])).status_code==409
    evidence=client.get(f"/tasks/{job['id']}/delivery").json()
    refused=client.post(f"/tasks/{job['id']}/delivery",json=dict(receipt=evidence['receipt'],action='export'))
    assert refused.status_code==409 and 'Accept' in refused.text
    accepted=client.post(f"/engineering-tasks/{task['id']}/accept",json=dict(revision=task['revision'],execution_task_id=job['id']))
    assert accepted.status_code==200,accepted.text
    assert accepted.json()['task']['status']=='done' and accepted.json()['current']['review_state']=='accepted'
    assert accepted.json()['current']['reviewed_at'] and store.get(job['id'])['delivery']=={}
    assert client.post(f"/engineering-tasks/{task['id']}/accept",json=dict(revision=task['revision'],execution_task_id=job['id'])).status_code==409
    cap=client.get(f"/workspace/members/{ai['id']}/capacity").json()
    assert cap['active_execution_count']==0 and cap['runtime_connected'] and cap['assigned_queue_depth']==3
    # Reopening API/store preserves history and human acceptance.
    reopened=TaskStore(str(store.engine.url.render_as_string(hide_password=False)))
    try:
        with TestClient(create_platform_app(config,reopened)) as other:
            restored=other.get(f"/engineering-tasks/{task['id']}/execution").json()
            assert restored['current']['review_state']=='accepted' and restored['task']['status']=='done'
            assert other.get(f"/tasks/{job['id']}").json()['engineering_origin']['ai_member_id']==ai['id']
    finally: reopened.close()


@pytest.mark.parametrize('condition',['unassigned','human','tester','reviewer','general','inactive','offline','membership','missing_membership','done','dependency'])
def test_start_eligibility_is_enforced_without_dependency_override(bridge,condition):
    client,app,store,planning,projects,ai,joins,config=bridge;task=first(bridge)
    if condition=='unassigned':
        assert client.delete(f'/engineering-tasks/{task.id}/assignment',params={'revision':task.revision}).status_code==200
    elif condition=='human':
        human=resource(client,name='Human');join(client,projects[0],human)
        client.post(f'/engineering-tasks/{task.id}/assignment',json=dict(assignee_id=human['id'],revision=task.revision))
    elif condition in {'tester','reviewer','general'}: edit_resource(client,ai,future_execution_role=condition)
    elif condition=='inactive': edit_resource(client,ai,active=False)
    elif condition=='offline': edit_resource(client,ai,availability='offline')
    elif condition=='membership':
        membership,squad=joins[0]
        assert client.patch(f"/project-memberships/{membership['id']}",json=dict(squad_id=squad['id'],active=False,revision=membership['revision'])).status_code==200
    elif condition=='missing_membership':
        from autonomous_engineering.infrastructure.team_tables import memberships
        with store.engine.begin() as db: db.execute(memberships.delete().where(memberships.c.id==joins[0][0]['id']))
    elif condition=='done': planning.set_status(task.id,EngineeringStatus.DONE,task.revision)
    elif condition=='dependency':
        from autonomous_engineering.infrastructure.planning_store import dependencies
        prerequisite=planning.latest(projects[0]['id']).plan.tasks[1]
        with store.engine.begin() as db: db.execute(dependencies.insert().values(task_id=str(task.id),depends_on_id=str(prerequisite.id)))
    result=start(bridge,planning.task(task.id))
    assert result.status_code==409,result.text
    assert store.list()==[]
    assert client.get(f'/engineering-tasks/{task.id}/executions').json()['executions']==[]


def test_queue_runtime_cross_project_concurrency_cancellation_and_fresh_retry(bridge):
    client,app,store,planning,projects,ai,joins,config=bridge
    task=first(bridge);result=start(bridge);assert result.status_code==202,result.text
    job_id=result.json()['execution']['id']
    assert result.json()['task']['status']=='in_progress'
    assert result.json()['eligibility']['active_execution_count']==1
    assert start(bridge,planning.task(task.id)).status_code==409
    assert start(bridge,first(bridge,1)).status_code==409
    assert client.delete(f'/engineering-tasks/{task.id}/assignment',params={'revision':planning.task(task.id).revision}).status_code==409
    assert client.patch(f'/engineering-tasks/{task.id}/status',json=dict(status='done',revision=planning.task(task.id).revision)).status_code==409
    membership,squad=joins[0]
    assert client.patch(f"/project-memberships/{membership['id']}",json=dict(squad_id=squad['id'],active=False,revision=membership['revision'])).status_code==409
    assert client.post(f'/tasks/{job_id}/cancel').status_code==202
    store.settle_interrupted()
    assert store.get(job_id)['phase']=='cancelled' and planning.task(task.id).status=='in_progress'
    retry=client.post(f'/tasks/{job_id}/retry');assert retry.status_code==202,retry.text
    current=client.get(f'/engineering-tasks/{task.id}/execution').json()
    assert len(current['history'])==2 and current['history'][0]['phase']=='cancelled'
    assert current['execution']['id']!=job_id and current['current']['run_id']!=result.json()['current']['run_id']
    cap=client.get(f"/workspace/members/{ai['id']}/capacity").json()
    assert cap['assigned_queue_depth']==4 and cap['active_execution_count']==1
    store.cancel(current['execution']['id']);store.settle_interrupted()
    assert start(bridge,first(bridge,1)).status_code==202


def test_two_simultaneous_cross_project_starts_reserve_only_one_slot(bridge):
    client,app,store,planning,projects,ai,joins,config=bridge
    gate=Barrier(2)
    def run(task):
        gate.wait();return start(bridge,task).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(run,[first(bridge),first(bridge,1)]))
    assert sorted(results)==[202,409]
    assert len(store.list())==1
    cap=client.get(f"/workspace/members/{ai['id']}/capacity").json()
    assert cap['active_execution_count']==1 and cap['assigned_queue_depth']==4


def test_creation_failure_rolls_back_job_events_link_and_board_state(bridge,monkeypatch):
    client,app,store,planning,projects,ai,joins,config=bridge;task=first(bridge)
    original=store.create_in_transaction
    def fail(db,state,options):
        original(db,state,options);raise RuntimeError('Injected queue failure')
    monkeypatch.setattr(store,'create_in_transaction',fail)
    with pytest.raises(RuntimeError,match='Injected queue failure'): start(bridge)
    assert planning.task(task.id)==task and store.list()==[]
    with store.engine.connect() as db:
        assert db.execute(select(events)).all()==[] and db.execute(select(execution_links)).all()==[]


def test_request_changes_creates_new_isolated_link_without_mutating_previous_snapshot(bridge):
    client,app,store,planning,projects,ai,joins,config=bridge
    result,worker,planner,developer=success(bridge);task=result['task'];job=result['execution'];original=store.get(job['id'])['snapshot']
    changes=client.post(f"/engineering-tasks/{task['id']}/request-changes",json=dict(revision=task['revision'],execution_task_id=job['id'],feedback='Also uppercase the greeting name'))
    assert changes.status_code==202,changes.text
    updated=changes.json();assert updated['task']['status']=='in_progress' and len(updated['history'])==2
    assert updated['history'][0]['review_state']=='changes_requested' and updated['history'][0]['feedback']=='Also uppercase the greeting name'
    assert store.get(job['id'])['snapshot']==original and updated['current']['parent_execution_task_id']==job['id']
    assert 'Human-requested changes' in updated['execution']['snapshot']['task']['request']['user_request']
    assert client.post(f"/engineering-tasks/{task['id']}/accept",json=dict(revision=updated['task']['revision'],execution_task_id=job['id'])).status_code==409
    new_worker,_,_=worker_for(bridge);assert new_worker.run_once()
    next_job=store.get(updated['execution']['id'])
    assert next_job['snapshot']['workspace_path']!=original['workspace_path'] and next_job['phase']=='awaiting_approval'
    store.cancel(next_job['id']);store.settle_interrupted()
    retry=client.post(f"/tasks/{next_job['id']}/retry")
    assert retry.status_code==202 and 'Also uppercase the greeting name' in store.get(retry.json()['id'])['snapshot']['task']['request']['user_request']


def test_failed_execution_preserves_in_progress_and_releases_slot(bridge):
    client,app,store,planning,projects,ai,joins,config=bridge
    result=start(bridge).json();job=store.claim('fixture-worker',60)
    state=WorkflowState.model_validate(job['snapshot']).apply(WorkflowUpdate(status=TaskStatus.RUNNING))
    state=state.apply(WorkflowUpdate(status=TaskStatus.FAILED,errors=[ExecutionError(code='FIXTURE_FAILURE',message='Tests failed after bounded repairs')],report=ReportSummary(outcome=TaskStatus.FAILED,summary='Explicit failure fixture')))
    store.checkpoint(job['id'],'fixture-worker',state,phase='failed')
    task=planning.task(first(bridge).id)
    assert task.status=='in_progress' and task.execution_run_id is not None
    assert client.get(f"/workspace/members/{ai['id']}/capacity").json()['active_execution_count']==0
    assert client.post(f'/engineering-tasks/{task.id}/accept',json=dict(revision=task.revision,execution_task_id=job['id'])).status_code==409
    assert start(bridge,task).status_code==202


def test_busy_administrative_setting_and_two_actual_slots_are_independent(bridge):
    client,app,store,planning,projects,ai,joins,config=bridge
    edit_resource(client,ai,availability='busy',max_concurrent_executions=2)
    assert start(bridge).status_code==202
    assert start(bridge,first(bridge,1)).status_code==202
    other=planning.latest(projects[0]['id']).plan.tasks[1]
    assert start(bridge,other).status_code==409
    capacity=client.get(f"/workspace/members/{ai['id']}/capacity").json()
    assert capacity['active_execution_count']==2 and len(capacity['active_executions'])==2 and capacity['assigned_queue_depth']==4
    assert client.get('/workspace/members').json()['members'][0]['availability']=='busy'


def test_finished_dependencies_allow_start_and_origin_checks_remain(bridge):
    client,app,store,planning,projects,ai,joins,config=bridge
    task=first(bridge);prerequisite=planning.latest(projects[0]['id']).plan.tasks[1]
    from autonomous_engineering.infrastructure.planning_store import dependencies
    with store.engine.begin() as db: db.execute(dependencies.insert().values(task_id=str(task.id),depends_on_id=str(prerequisite.id)))
    planning.set_status(prerequisite.id,EngineeringStatus.DONE,prerequisite.revision)
    refused=client.post(f'/engineering-tasks/{task.id}/executions',json=dict(revision=task.revision),headers={'Origin':'https://evil.test'})
    assert refused.status_code==403 and store.list()==[]
    result=start(bridge);assert result.status_code==202
    assert 'Completed prerequisites' in result.json()['execution']['snapshot']['task']['request']['user_request']


def test_same_task_race_does_not_create_duplicate_runs(bridge):
    gate=Barrier(2);task=first(bridge)
    def run(_):
        gate.wait();return start(bridge,task).status_code
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(run,range(2)))
    assert sorted(results)==[202,409] and len(bridge[2].list())==1


def test_acceptance_refuses_modified_reviewed_snapshot_and_invalid_execution_id(bridge):
    result,_,_,_=success(bridge)
    task=result['task'];job=result['execution'];client=bridge[0]
    assert client.post(f"/engineering-tasks/{task['id']}/accept",json=dict(revision=task['revision'],execution_task_id='invalid')).status_code==422
    Path(job['snapshot']['workspace_path'],'app.py').write_text('changed after review\n',encoding='utf-8')
    rejected=client.post(f"/engineering-tasks/{task['id']}/accept",json=dict(revision=task['revision'],execution_task_id=job['id']))
    assert rejected.status_code==409 and 'changed' in rejected.text
    assert bridge[3].task(task['id']).status=='review' and bridge[2].get(job['id'])['delivery']=={}


def test_explicit_delivery_reuses_existing_export_after_acceptance(bridge,monkeypatch):
    import shutil
    git_dir=Path(r'C:\Program Files\Git\cmd')
    if git_dir.is_dir():monkeypatch.setenv('PATH',str(git_dir)+os.pathsep+os.environ['PATH'])
    if not shutil.which('git'):pytest.skip('Git required for commit export')
    result,_,_,_=success(bridge);task=result['task'];job=result['execution'];client=bridge[0]
    accepted=client.post(f"/engineering-tasks/{task['id']}/accept",json=dict(revision=task['revision'],execution_task_id=job['id']))
    assert accepted.status_code==200 and bridge[2].get(job['id'])['delivery']=={}
    evidence=client.get(f"/tasks/{job['id']}/delivery").json()
    exported=client.post(f"/tasks/{job['id']}/delivery",json=dict(receipt=evidence['receipt'],action='export'))
    assert exported.status_code==200,exported.text
    assert len(exported.json()['commit'])==40 and Path(exported.json()['archive']).is_file()
    assert Path(bridge[4][0]['path'],'app.py').read_text().endswith('+ name\n')
