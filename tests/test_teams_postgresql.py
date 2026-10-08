"""Optional real PostgreSQL coverage, using an explicit disposable database."""
import os
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from autonomous_engineering.core.config import Settings
from autonomous_engineering.domain.teams import SquadInput, ProjectMemberInput, ApplyAssignments
from autonomous_engineering.infrastructure.task_store import TaskStore
from autonomous_engineering.infrastructure.planning_store import PlanningStore
from autonomous_engineering.infrastructure.team_store import TeamStore
from autonomous_engineering.application.worker import Worker
from autonomous_engineering.platform import create_platform_app
from test_product_planning import Provider


@pytest.mark.skipif(not os.environ.get('ASE_INTEGRATION_DATABASE_URL'), reason='Explicit PostgreSQL integration opt-in')
def test_postgresql_team_persistence_capacity_and_atomic_suggestions(tmp_path):
    config = Settings(_env_file=None,environment='test',repository_root=tmp_path,workspace_root=tmp_path/'snapshots')
    store = TaskStore(os.environ['ASE_INTEGRATION_DATABASE_URL'])
    try:
        assert store.engine.dialect.name == 'postgresql'
        source = tmp_path / str(uuid4()); source.mkdir(); (source/'app.py').write_text('value = 1\n')
        project = store.register(str(source),dict(name='PostgreSQL integration fixture',description='',stack=[]))
        planning = PlanningStore(store.engine)
        planning.enqueue(project['id'],'Fixture authentication')
        assert Worker(config,store,product_plan_provider=Provider()).run_once()
        record=planning.latest(project['id']); planning.approve(record.goal.id,record.draft_revision)
        teams = TeamStore(planning)
        squad = teams.save_squad(project['id'],SquadInput(name='Core',technical_areas=['Backend','Database']))
        human = teams.save_member(project['id'],ProjectMemberInput(name='Fixture human',role='Engineer',member_type='human',squad_id=squad.id,
            weekly_capacity_hours=30,target_utilization=.8,skills=[dict(technical_area='Database',proficiency=5),dict(technical_area='Backend',proficiency=5)]))
        ai = teams.save_member(project['id'],ProjectMemberInput(name='Fixture AI',role='Developer',member_type='ai',squad_id=squad.id,
            availability='available',max_concurrent_tasks=1,future_execution_role='developer',skills=[dict(technical_area='Backend',proficiency=4)]))
        proposal = teams.suggested_plan(project['id'])
        assert len(proposal['suggestions']) == 2
        body = ApplyAssignments.model_validate(dict(project_revision=proposal['project_revision'],workspace_revision=proposal['workspace_revision'],assignments=[{key:item[key] for key in ('task_id','assignee_id','revision')} for item in proposal['suggestions']]))
        applied = teams.apply(project['id'],body)
        assert next(item for item in applied['capacities'] if str(item.member_id)==str(human['id'])).planned_load_hours == 6
        assert all(item.assignee_id for item in applied['tasks'])
        with TestClient(create_platform_app(config,store)) as client:
            first = applied['tasks'][0]
            assert client.patch(f'/engineering-tasks/{first.id}/status',json=dict(status='done',revision=first.revision)).status_code == 200
            assert client.post(f"/projects/{project['id']}/apply-assignment-recommendations",json=body.model_dump(mode='json')).status_code == 409
        reopened = TaskStore(os.environ['ASE_INTEGRATION_DATABASE_URL'])
        try:
            restored = TeamStore(PlanningStore(reopened.engine)).snapshot(project['id'])
            assert len(restored['squads']) == 1 and len(restored['members']) == 2
            assert restored['tasks'][0].status == 'done'
            assert next(item for item in restored['capacities'] if str(item.member_id)==str(human['id'])).planned_load_hours == 4
        finally: reopened.close()
    finally: store.close()
