"""Real SQL resource planning behavior; fixture identities never seed the product."""
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from autonomous_engineering.core.config import Settings

from autonomous_engineering.domain.teams import SquadInput, MemberInput
from autonomous_engineering.infrastructure.planning_store import PlanningStore
from autonomous_engineering.infrastructure.task_store import TaskStore
from autonomous_engineering.infrastructure.team_store import TeamStore
from autonomous_engineering.platform import create_platform_app
from autonomous_engineering.application.worker import Worker
from test_product_planning import product, Provider


@pytest.fixture
def team(product):
    config, store, planning, project = product
    planning.enqueue(project['id'], 'Fixture authentication')
    Worker(config, store, product_plan_provider=Provider()).run_once()
    record=planning.latest(project['id']); planning.approve(record.goal.id,record.draft_revision)
    client = TestClient(create_platform_app(config, store))
    with client:
        yield client, project, planning, TeamStore(planning), store


def squad(client, project, name='Core', areas=None):
    response = client.post(f"/projects/{project['id']}/squads", json=dict(name=name, description='Fixture squad', technical_areas=areas or ['Backend', 'Database']))
    assert response.status_code == 201, response.text
    return response.json()


def member(client, project, squad, name='Human', ai=False, **extra):
    body = dict(name=name, role='Engineer', member_type='ai' if ai else 'human', squad_id=squad['id'],
        skills=[dict(technical_area='Backend', proficiency=5), dict(technical_area='Database', proficiency=4)])
    body.update(dict(availability='available', max_concurrent_tasks=1, future_execution_role='developer') if ai else dict(weekly_capacity_hours=30, target_utilization=.8))
    body.update(extra)
    response = client.post(f"/projects/{project['id']}/members", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def assign(client, task, person, **extra):
    return client.post(f"/engineering-tasks/{task['id']}/assignment", json=dict(assignee_id=person['id'], revision=task['revision'], **extra))


def tasks(client, project):
    return client.get(f"/projects/{project['id']}/teams").json()['tasks']


def test_persistence_capacity_reassignment_removal_and_done(team):
    client, project, planning, teams, store = team
    core = squad(client, project)
    taha = member(client, project, core)
    other = member(client, project, core, 'Other')
    first, second = tasks(client, project)
    response = assign(client, first, taha)
    assert response.status_code == 200
    first = response.json()['task']
    assert first['execution_run_id'] is None
    assert assign(client, second, taha).status_code == 409  # Uncompleted dependency requires explicit decision.
    second = assign(client, second, taha, override_warnings=True).json()['task']
    summary = client.get(f"/projects/{project['id']}/teams").json()
    load = next(item for item in summary['capacities'] if item['member_id'] == taha['id'])
    assert load['assignable_capacity_hours'] == 24 and load['reserved_capacity_hours'] == 6
    assert load['planned_load_hours'] == 6 and load['remaining_capacity_hours'] == 18
    assert assign(client, first, taha).status_code == 200  # Same owner never doubles load.
    first = tasks(client, project)[0]
    first = assign(client, first, other).json()['task']
    assert client.patch(f"/engineering-tasks/{second['id']}/status", json=dict(status='done', revision=second['revision'])).status_code == 200
    summary = teams.snapshot(project['id'])
    assert next(item for item in summary['capacities'] if str(item.member_id) == taha['id']).planned_load_hours == 0
    assert next(item for item in summary['capacities'] if str(item.member_id) == other['id']).planned_load_hours == 2
    restored = TaskStore(str(store.engine.url))
    try:
        reopened = TeamStore(PlanningStore(restored.engine)).snapshot(project['id'])
        assert len(reopened['squads']) == 1 and len(reopened['members']) == 2
        assert str(reopened['tasks'][0].assignee_id) == other['id']
    finally: restored.close()
    assert client.delete(f"/engineering-tasks/{first['id']}/assignment", params={'revision':first['revision']}).status_code == 200
    assert teams.snapshot(project['id'])['tasks'][0].assignee_id is None
    assert store.list() == []


def test_manual_over_capacity_override_and_stale_revision(team):
    client, project, planning, teams, store = team
    core = squad(client, project)
    person = member(client, project, core, weekly_capacity_hours=1, target_utilization=.8)
    task = tasks(client, project)[0]
    warning = assign(client, task, person)
    assert warning.status_code == 409 and '1.2h' in warning.json()['detail']['warnings'][0]
    assert planning.task(task['id']).revision == 0
    changed = assign(client, task, person, override_warnings=True)
    assert changed.status_code == 200
    assert teams.snapshot(project['id'])['capacities'][0].remaining_capacity_hours == -1.2
    assert assign(client, task, person, override_warnings=True).status_code == 409
    assert client.delete(f"/engineering-tasks/{task['id']}/assignment", params={'revision':0}).status_code == 409


def test_recommendation_ranking_skill_availability_and_nonmutation(team):
    client, project, planning, teams, store = team
    core = squad(client, project)
    good = member(client, project, core, 'Fit')
    member(client, project, core, 'Low capacity', weekly_capacity_hours=1)
    member(client, project, core, 'Inactive', active=False)
    member(client, project, core, 'Offline', ai=True, availability='offline')
    member(client, project, core, 'Busy', ai=True, availability='busy')
    member(client, project, core, 'Unskilled', skills=[dict(technical_area='Frontend', proficiency=5)])
    ai = member(client, project, core, 'AI', ai=True, skills=[dict(technical_area='Backend', proficiency=4)])
    task = tasks(client, project)[1]
    recommendations = client.get(f"/engineering-tasks/{task['id']}/recommendations").json()
    choices = recommendations['recommendations']
    assert choices[0]['member_id'] == good['id']
    assert len(choices) == 3 and not choices[-1]['fits_capacity']
    assert choices[1]['member_id'] == ai['id']
    assert choices[1]['remaining_capacity_hours'] is None
    assert recommendations['warnings'] and 'CO-1' in recommendations['warnings'][0]
    assert all(task.assignee_id is None for task in teams.snapshot(project['id'])['tasks'])


def test_bulk_suggestions_projected_load_explicit_apply_and_stale(team):
    client, project, planning, teams, store = team
    core = squad(client, project)
    person = member(client, project, core, weekly_capacity_hours=5, target_utilization=1)
    ai = member(client, project, core, 'AI', ai=True)
    before = teams.snapshot(project['id'])
    suggestion = client.get(f"/projects/{project['id']}/assignment-recommendations").json()
    assert len(suggestion['suggestions']) == 2
    assert len({item['assignee_id'] for item in suggestion['suggestions']}) == 2
    assert teams.snapshot(project['id']) == before
    payload = dict(project_revision=suggestion['project_revision'], workspace_revision=suggestion['workspace_revision'], assignments=[{key:item[key] for key in ('task_id','assignee_id','revision')} for item in suggestion['suggestions']])
    result = client.post(f"/projects/{project['id']}/apply-assignment-recommendations", json=payload)
    assert result.status_code == 200, result.text
    assert all(task['assignee_id'] for task in result.json()['tasks'])
    assert client.post(f"/projects/{project['id']}/apply-assignment-recommendations", json=payload).status_code == 409
    assert client.get(f"/projects/{project['id']}/assignment-recommendations").json()['suggestions'] == []


def test_bulk_application_rolls_back_when_combined_capacity_does_not_fit(team):
    client, project, planning, teams, store = team
    core = squad(client, project)
    person = member(client, project, core, weekly_capacity_hours=5, target_utilization=1)
    snapshot = client.get(f"/projects/{project['id']}/teams").json()
    payload = dict(project_revision=snapshot['project_revision'], workspace_revision=snapshot['workspace_revision'], assignments=[dict(task_id=t['id'], assignee_id=person['id'], revision=t['revision']) for t in snapshot['tasks']])
    assert client.post(f"/projects/{project['id']}/apply-assignment-recommendations", json=payload).status_code == 409
    assert all(task.assignee_id is None and task.revision == 0 for task in teams.snapshot(project['id'])['tasks'])


def test_project_isolation_edits_and_squad_only_assignment(team):
    client, project, planning, teams, store = team
    core = squad(client, project)
    person = member(client, project, core)
    other = store.register(project['path'] + '-other', dict(name='Other', description='', stack=[]))
    foreign_squad = squad(client, other)
    foreign_member = member(client, other, foreign_squad)
    task = tasks(client, project)[0]
    assert assign(client, task, foreign_member).status_code == 404
    assert client.post(f"/projects/{project['id']}/members", json={key:value for key,value in foreign_member.items() if key not in ('id','project_id','revision','created_at')}).status_code == 404
    assigned = client.post(f"/engineering-tasks/{task['id']}/assignment", json=dict(squad_id=core['id'],revision=0)).json()['task']
    assert assigned['squad_id'] == core['id'] and assigned['assignee_id'] is None
    change = dict(name='Renamed', description='Edited', technical_areas=['Backend'], revision=0)
    assert client.patch(f"/squads/{core['id']}", json=change).status_code == 200
    assert client.patch(f"/squads/{core['id']}", json=change).status_code == 409
    new_squad = squad(client, project, 'New')
    assigned = assign(client, assigned, person, override_warnings=True).json()['task']
    edit = {key:value for key,value in person.items() if key not in ('id','project_id','squad_id','created_at')}
    edit['skills'] = [dict(technical_area='Database',proficiency=3)]
    assert client.patch(f"/members/{person['id']}", json=edit).status_code == 200
    assert client.patch(f"/members/{person['id']}", json=edit).status_code == 409
    joined = teams.snapshot(project['id'])['memberships'][0]
    response = client.patch(f'/project-memberships/{joined.id}', json=dict(squad_id=new_squad['id'],active=True,revision=joined.revision))
    assert response.status_code == 200
    assert str(planning.task(task['id']).squad_id) == new_squad['id']
    assert planning.task(task['id']).revision == assigned['revision'] + 1


def test_ai_queue_and_done_release(team):
    client, project, planning, teams, store = team
    core = squad(client, project)
    ai = member(client, project, core, ai=True)
    first, second = tasks(client, project)
    first = assign(client, first, ai).json()['task']
    recommendations = client.get(f"/engineering-tasks/{second['id']}/recommendations").json()['recommendations']
    assert recommendations[0]['fits_capacity'] and recommendations[0]['assigned_queue_depth'] == 1
    queued = assign(client, second, ai, override_warnings=True)
    assert queued.status_code == 200
    capacity = teams.snapshot(project['id'])['capacities'][0]
    assert capacity.assigned_queue_depth == 2 and capacity.max_concurrent_executions == 1
    assert capacity.active_execution_count == 0 and capacity.runtime_connected
    assert assign(client, second, ai).status_code == 409
    assert client.patch(f"/engineering-tasks/{first['id']}/status",json=dict(status='done',revision=first['revision'])).status_code == 200
    assert teams.snapshot(project['id'])['capacities'][0].assigned_queue_depth == 1


def test_status_or_member_edit_invalidates_suggestions(team):
    client, project, planning, teams, store = team
    core = squad(client, project)
    person = member(client, project, core)
    proposal = client.get(f"/projects/{project['id']}/assignment-recommendations").json()
    task = tasks(client, project)[0]
    client.patch(f"/engineering-tasks/{task['id']}/status",json=dict(status='planned',revision=task['revision']))
    payload = dict(project_revision=proposal['project_revision'], workspace_revision=proposal['workspace_revision'],assignments=[{key:value for key,value in item.items() if key in ('task_id','assignee_id','revision')} for item in proposal['suggestions']])
    assert client.post(f"/projects/{project['id']}/apply-assignment-recommendations",json=payload).status_code == 409
    assert all(task.assignee_id is None for task in teams.snapshot(project['id'])['tasks'])


def test_team_routes_origin_unknown_and_invalid_capacity(team):
    client, project, planning, teams, store = team
    assert client.get(f'/projects/{uuid4()}/teams').status_code == 404
    assert client.get(f'/engineering-tasks/{uuid4()}/recommendations').status_code == 404
    assert client.post(f"/projects/{project['id']}/squads",json=dict(name='Core',technical_areas=['Backend']),headers={'Origin':'https://evil.test'}).status_code == 403
    core = squad(client, project)
    assert client.post(f"/projects/{project['id']}/members",json=dict(name='AI',role='Developer',member_type='ai',squad_id=core['id'],skills=[dict(technical_area='Backend',proficiency=5)],weekly_capacity_hours=40)).status_code == 422
    with pytest.raises(ValidationError): SquadInput(name='Core',technical_areas=['Backend','Backend'])


def test_concurrent_assignments_cannot_silently_overallocate(team):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import delete
    from autonomous_engineering.infrastructure.planning_store import dependencies
    client, project, planning, teams, store = team
    core = squad(client, project)
    person = member(client, project, core, weekly_capacity_hours=4, target_utilization=1)
    first, second = tasks(client, project)
    with store.engine.begin() as db:
        db.execute(delete(dependencies))  # Remove the fixture dependency to test only capacity contention.
    barrier = Barrier(2)
    def competing(task):
        barrier.wait(timeout=5)
        return assign(client, task, person).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(competing,[first,second]))
    assert sorted(results) == [200,409]
    capacity = teams.snapshot(project['id'])['capacities'][0]
    assert capacity.planned_load_hours <= capacity.assignable_capacity_hours


def test_previous_plan_load_reopening_and_inactivation_are_retained(team):
    client, project, planning, teams, store = team
    core = squad(client, project)
    person = member(client, project, core)
    first = assign(client,tasks(client,project)[0],person).json()['task']
    planning.enqueue(project['id'],'New fixture goal')
    config = Settings(_env_file=None,environment='test')
    Worker(config,store,product_plan_provider=Provider()).run_once()
    assert planning.latest(project['id']).status=='draft'
    snapshot=teams.snapshot(project['id'])
    assert len(snapshot['tasks'])==2 and snapshot['capacities'][0].planned_load_hours==2
    assert snapshot['current_plan_id']==str(planning.task(first['id']).plan_id)
    record=planning.latest(project['id']); planning.approve(record.goal.id,record.draft_revision)
    assert teams.snapshot(project['id'])['capacities'][0].planned_load_hours == 2
    assert all(str(task.assignee_id) != person['id'] for task in planning.latest(project['id']).plan.tasks)
    first = client.patch(f"/engineering-tasks/{first['id']}/status",json=dict(status='done',revision=first['revision'])).json()
    assert teams.snapshot(project['id'])['capacities'][0].planned_load_hours == 0
    client.patch(f"/engineering-tasks/{first['id']}/status",json=dict(status='planned',revision=first['revision']))
    assert teams.snapshot(project['id'])['capacities'][0].planned_load_hours == 2
    edit = {key:value for key,value in person.items() if key not in ('id','project_id','squad_id','created_at')}
    edit['active'] = False
    assert client.patch(f"/members/{person['id']}",json=edit).status_code == 200
    assert teams.snapshot(project['id'])['capacities'][0].planned_load_hours == 2
    assert teams.recommendations(planning.latest(project['id']).plan.tasks[0].id)['recommendations'] == []
