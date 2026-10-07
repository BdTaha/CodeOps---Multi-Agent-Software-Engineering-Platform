"""Cross-project resources, queue semantics, revision fences and real contention."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from autonomous_engineering.core.config import Settings
from autonomous_engineering.domain.product_planning import ProductPlanDraft
from autonomous_engineering.infrastructure.task_store import TaskStore
from autonomous_engineering.infrastructure.planning_store import PlanningStore
from autonomous_engineering.infrastructure.team_store import TeamStore
from autonomous_engineering.platform import create_platform_app
from test_product_planning import draft_data


@pytest.fixture(params=['sqlite','postgresql'])
def shared(request,tmp_path):
    if request.param=='postgresql' and not os.environ.get('ASE_INTEGRATION_DATABASE_URL'):
        pytest.skip('Explicit PostgreSQL integration opt-in')
    url=os.environ['ASE_INTEGRATION_DATABASE_URL'] if request.param=='postgresql' else 'sqlite:///'+str(tmp_path/'shared.db')
    store=TaskStore(url)
    planning=PlanningStore(store.engine)
    project_list=[]
    for name,estimates in [('Project A',(14,4)),('Project B',(7,5))]:
        source=tmp_path/str(uuid4());source.mkdir()
        project=store.register(str(source),dict(name=name,description='Explicit test fixture',stack=[]))
        data=draft_data()
        for task,estimate in zip(data['tasks'],estimates):
            task.update(estimated_hours=estimate,technical_area='Backend',dependencies=[])
        record=planning.enqueue(project['id'],'Fixture cross-project plan')
        planning.claim('fixture',60)
        planning.complete(str(record.goal.id),'fixture',ProductPlanDraft.model_validate(data),1,'explicit-fixture')
        project_list.append(project)
    config=Settings(_env_file=None,environment='test',repository_root=tmp_path,workspace_root=tmp_path/'snapshots')
    with TestClient(create_platform_app(config,store)) as client:
        yield client,project_list,planning,TeamStore(planning),store
    store.close()


def resource(client,ai=False,name='Shared human',**extra):
    body=dict(name=name,role='Backend Engineer',member_type='ai' if ai else 'human',skills=[dict(technical_area='Backend',proficiency=5)])
    body.update(dict(availability='available',max_concurrent_executions=1,future_execution_role='developer') if ai else dict(weekly_capacity_hours=30,target_utilization=.8))
    body.update(extra)
    result=client.post('/workspace/members',json=body)
    assert result.status_code==201,result.text
    return result.json()


def join(client,project,member,name='Backend'):
    squad=client.post(f"/projects/{project['id']}/squads",json=dict(name=name,technical_areas=['Backend'])).json()
    result=client.post(f"/projects/{project['id']}/memberships",json=dict(member_id=member['id'],squad_id=squad['id']))
    assert result.status_code==201,result.text
    return result.json(),squad


def edit_resource(client,person,**changes):
    body={key:value for key,value in person.items() if key not in ('id','created_at')}
    body.update(changes)
    result=client.patch(f"/workspace/members/{person['id']}",json=body)
    assert result.status_code==200,result.text
    return result.json()


def assign(client,task,person,override=False):
    result=client.post(f'/engineering-tasks/{task.id}/assignment',json=dict(assignee_id=person['id'],revision=task.revision,override_warnings=override))
    return result


def test_identity_global_capacity_and_project_breakdown(shared):
    client,projects,planning,teams,store=shared
    existing_execution_ids = {item['id'] for item in store.list()}
    human=resource(client)
    for project,name in zip(projects,['Backend','Platform']): join(client,project,human,name)
    for project in projects:
        assert assign(client,planning.latest(project['id']).plan.tasks[0],human).status_code==200
    capacity=client.get(f"/workspace/members/{human['id']}/capacity").json()
    assert capacity['planned_load_hours']==21 and capacity['assignable_capacity_hours']==24
    assert capacity['remaining_capacity_hours']==3 and capacity['reserved_capacity_hours']==6
    assert sorted(item['planned_load_hours'] for item in capacity['project_breakdown'])==[7,14]
    for project in projects:
        snapshot=teams.snapshot(project['id'])
        assert next(item for item in snapshot['capacities'] if str(item.member_id)==human['id']).remaining_capacity_hours==3
        task=planning.latest(project['id']).plan.tasks[1]
        choices=teams.recommendations(task.id)['recommendations']
        assert not choices[0].fits_capacity and choices[0].remaining_capacity_hours==3
        assert assign(client,task,human).status_code==409
    assert {item['id'] for item in store.list()} == existing_execution_ids
    project_ids = {item['id'] for item in projects}
    assert all(task.execution_run_id is None for task in teams.workspace_snapshot()['tasks'] if str(task.project_id) in project_ids)


def test_membership_isolation_squad_moves_and_inactivation(shared):
    client,projects,planning,teams,store=shared
    person=resource(client)
    membership_a,squad_a=join(client,projects[0],person,'Backend')
    task_b=planning.latest(projects[1]['id']).plan.tasks[0]
    assert assign(client,task_b,person).status_code==404
    membership_b,squad_b=join(client,projects[1],person,'Platform')
    first_a=planning.latest(projects[0]['id']).plan.tasks[0]
    assert assign(client,first_a,person).status_code==200
    new_squad=client.post(f"/projects/{projects[0]['id']}/squads",json=dict(name='New A',technical_areas=['Backend'])).json()
    response=client.patch(f"/project-memberships/{membership_a['id']}",json=dict(squad_id=new_squad['id'],active=False,revision=membership_a['revision']))
    assert response.status_code==200
    assert str(planning.task(first_a.id).squad_id)==new_squad['id']
    assert str(teams.membership(membership_b['id']).squad_id)==squad_b['id']
    assert teams.membership(membership_b['id']).active
    assert teams.recommendations(planning.latest(projects[0]['id']).plan.tasks[1].id)['recommendations']==[]
    assert teams.recommendations(task_b.id)['recommendations']
    assert assign(client,planning.latest(projects[0]['id']).plan.tasks[1],person,True).status_code==409
    assert client.patch(f"/project-memberships/{membership_a['id']}",json=dict(squad_id=squad_b['id'],active=True,revision=response.json()['revision'])).status_code==404
    assert client.post(f"/projects/{projects[1]['id']}/memberships",json=dict(member_id=person['id'],squad_id=squad_b['id'])).status_code==409
    assert client.patch(f"/project-memberships/{membership_a['id']}",json=dict(squad_id=new_squad['id'],active=True,revision=0)).status_code==409


def test_workspace_skills_capacity_and_active_state_apply_everywhere(shared):
    client,projects,planning,teams,store=shared
    person=resource(client)
    for project in projects: join(client,project,person)
    person=edit_resource(client,person,skills=[dict(technical_area='Frontend',proficiency=5)])
    assert all(teams.recommendations(planning.latest(project['id']).plan.tasks[0].id)['recommendations']==[] for project in projects)
    person=edit_resource(client,person,skills=[dict(technical_area='Backend',proficiency=5)],weekly_capacity_hours=10)
    for project in projects:
        cap=next(item for item in teams.snapshot(project['id'])['capacities'] if str(item.member_id)==person['id'])
        assert cap.assignable_capacity_hours==8
    person=edit_resource(client,person,active=False)
    assert all(teams.recommendations(planning.latest(project['id']).plan.tasks[0].id)['recommendations']==[] for project in projects)


def test_cross_project_competing_assignments_use_global_lock(shared):
    client,projects,planning,teams,store=shared
    person=resource(client,weekly_capacity_hours=5,target_utilization=1)
    for project in projects: join(client,project,person)
    tasks=[planning.latest(project['id']).plan.tasks[1] for project in projects]  # 4h and 5h; each fits alone.
    barrier=Barrier(2)
    def competing(task):
        barrier.wait(timeout=5)
        return assign(client,task,person).status_code
    with ThreadPoolExecutor(max_workers=2) as pool: result=list(pool.map(competing,tasks))
    assert sorted(result)==[200,409]
    cap=client.get(f"/workspace/members/{person['id']}/capacity").json()
    assert cap['planned_load_hours'] in (4,5) and cap['remaining_capacity_hours']>=0


def test_global_projected_batch_and_workspace_staleness(shared):
    client,projects,planning,teams,store=shared
    person=resource(client)
    for project in projects: join(client,project,person)
    # Project A consumes 18h; B may suggest 7h only after capacity is raised.
    for task in planning.latest(projects[0]['id']).plan.tasks: assert assign(client,task,person).status_code==200
    proposal=client.get(f"/projects/{projects[1]['id']}/assignment-recommendations").json()
    assert [item['key'] for item in proposal['suggestions']]==['CO-2']  # 7h does not fit; 5h fits remaining 6h.
    person=edit_resource(client,person,weekly_capacity_hours=32.5)  # 26h budget; B's 7h then leaves 1h.
    proposal=client.get(f"/projects/{projects[1]['id']}/assignment-recommendations").json()
    assert [item['key'] for item in proposal['suggestions']]==['CO-1']
    old_revision=proposal['workspace_revision']
    person=edit_resource(client,person,role='Updated globally')
    body=dict(project_revision=proposal['project_revision'],workspace_revision=old_revision,assignments=[{key:item[key] for key in ('task_id','assignee_id','revision')} for item in proposal['suggestions']])
    assert client.post(f"/projects/{projects[1]['id']}/apply-assignment-recommendations",json=body).status_code==409
    assert all(task.assignee_id is None for task in planning.latest(projects[1]['id']).plan.tasks)


def test_ai_queue_is_global_soft_balance_not_runtime_capacity(shared):
    client,projects,planning,teams,store=shared
    first=resource(client,True,'Agent A')
    second=resource(client,True,'Agent B')
    lower=resource(client,True,'Less skilled',skills=[dict(technical_area='Backend',proficiency=4)])
    for project in projects:
        for person in (first,second,lower): join(client,project,person,person['name'])
    for task in planning.latest(projects[0]['id']).plan.tasks:
        response=assign(client,task,first)
        assert response.status_code==200,response.text
    third=planning.latest(projects[1]['id']).plan.tasks[0]
    options=teams.recommendations(third.id)['recommendations']
    assert str(options[0].member_id)==second['id']
    assert str(options[1].member_id)==first['id'] and options[1].fits_capacity
    assert str(options[2].member_id)==lower['id']  # Queue balance cannot overpower skill.
    assert assign(client,third,first).status_code==200
    cap=client.get(f"/workspace/members/{first['id']}/capacity").json()
    assert cap['assigned_queue_depth']==3 and cap['max_concurrent_executions']==1
    assert cap['active_execution_count'] is None and not cap['runtime_connected']
    assert cap['planned_load_hours'] is None and cap['remaining_capacity_hours'] is None
    assert sorted(item['assigned_task_count'] for item in cap['project_breakdown'])==[1,2]
    first=edit_resource(client,first,availability='offline')
    second=edit_resource(client,second,availability='busy')
    options=teams.recommendations(planning.latest(projects[1]['id']).plan.tasks[1].id)['recommendations']
    assert [str(item.member_id) for item in options]==[lower['id']]
    warning=assign(client,planning.latest(projects[1]['id']).plan.tasks[1],second)
    assert warning.status_code==409 and any('busy' in text for text in warning.json()['detail']['warnings'])
    assert not any('slots' in text or 'concurrency' in text for text in warning.json()['detail']['warnings'])


def test_new_schema_and_workspace_origin_validation(shared):
    from sqlalchemy import inspect
    client,projects,planning,teams,store=shared
    if store.engine.dialect.name=='sqlite': assert not inspect(store.engine).has_table('team_members')
    assert inspect(store.engine).has_table('workspace_members')
    assert client.post('/workspace/members',json={},headers={'Origin':'https://elsewhere.test'}).status_code in (403,422)
    assert client.get(f'/workspace/members/{uuid4()}/capacity').status_code==404
    person=resource(client)
    body={key:value for key,value in person.items() if key not in ('id','created_at')}
    assert client.patch(f"/workspace/members/{person['id']}",json=body,headers={'Origin':'https://elsewhere.test'}).status_code==403
