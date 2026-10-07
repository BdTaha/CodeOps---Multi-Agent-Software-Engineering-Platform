"""An actual old relational schema, including its assignment foreign key."""
import os
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, MetaData, Table, Column, String, Text, Float, Integer, Boolean, ForeignKey, insert, select, inspect, event
from autonomous_engineering.domain.base import utc_now
from autonomous_engineering.infrastructure.task_store import metadata, projects
from autonomous_engineering.infrastructure.planning_store import PlanningStore, goals, epics, engineering_tasks
from autonomous_engineering.infrastructure.team_tables import TEAM_TABLES, squads, members, skills, memberships, assignments, migrations
from autonomous_engineering.infrastructure.team_store import TeamStore


@pytest.fixture(params=['sqlite','postgresql'])
def legacy(request,tmp_path):
    if request.param=='postgresql' and not os.environ.get('ASE_INTEGRATION_DATABASE_URL'):
        pytest.skip('Explicit PostgreSQL integration opt-in')
    # PostgreSQL uses a dedicated schema: no shared test/user tables are dropped.
    schema='legacy_'+uuid4().hex if request.param=='postgresql' else None
    root_engine=create_engine(os.environ['ASE_INTEGRATION_DATABASE_URL'] if schema else 'sqlite:///'+str(tmp_path/'legacy.db'))
    if schema:
        with root_engine.begin() as db: db.exec_driver_sql(f'CREATE SCHEMA {schema}')
        engine=create_engine(os.environ['ASE_INTEGRATION_DATABASE_URL'],connect_args={'options':f'-csearch_path={schema}'})
    else:
        engine=root_engine
        @event.listens_for(engine,'connect')
        def foreign_keys(connection,_): connection.execute('PRAGMA foreign_keys=ON')
    base_tables=[table for table in metadata.sorted_tables if table not in TEAM_TABLES]
    metadata.create_all(engine,tables=base_tables+[squads])
    old=MetaData()
    for table in metadata.sorted_tables:
        if table not in TEAM_TABLES or table is squads: table.to_metadata(old)
    old_members=Table('team_members',old,
        Column('id',String(36),primary_key=True),Column('project_id',String(36),ForeignKey('projects.id'),nullable=False),
        Column('squad_id',String(36),ForeignKey('team_squads.id'),nullable=False),
        Column('name',String(200),nullable=False),Column('role',String(200),nullable=False),
        Column('member_type',String(10),nullable=False),Column('active',Boolean,nullable=False),
        Column('weekly_capacity_hours',Float),Column('target_utilization',Float),Column('availability',String(20)),
        Column('max_concurrent_tasks',Integer),Column('future_execution_role',String(20)),
        Column('created_at',String(40),nullable=False),Column('revision',Integer,nullable=False))
    old_skills=Table('team_member_skills',old,Column('member_id',String(36),ForeignKey('team_members.id'),primary_key=True),
        Column('technical_area',String(20),primary_key=True),Column('proficiency',Integer,nullable=False))
    old_assignments=Table('engineering_task_assignments',old,
        Column('task_id',String(36),ForeignKey('engineering_tasks.id'),primary_key=True),
        Column('squad_id',String(36),ForeignKey('team_squads.id'),nullable=False),Column('assignee_id',String(36),ForeignKey('team_members.id')),
        Column('created_at',String(40),nullable=False))
    old.create_all(engine,tables=[old_members,old_skills,old_assignments])
    now=utc_now().isoformat();identities=[]
    with engine.begin() as db:
        for kind in ('human','human','ai'):
            project_id,goal_id,epic_id,task_id,squad_id,member_id=[str(uuid4()) for _ in range(6)]
            db.execute(insert(projects).values(id=project_id,path='fixture/'+project_id,data='{"name":"Legacy fixture","description":"","stack":[]}'))
            db.execute(insert(goals).values(id=goal_id,project_id=project_id,goal='Legacy goal',created_at=now,status='ready',revision=0,attempts=1,title='Legacy plan',summary='Legacy plan',assumptions='[]'))
            db.execute(insert(epics).values(id=epic_id,plan_id=goal_id,position=0,title='Legacy epic',description='Legacy epic'))
            db.execute(insert(engineering_tasks).values(id=task_id,project_id=project_id,plan_id=goal_id,epic_id=epic_id,number=1,title='Legacy task',description='Legacy task',status='planned',priority='high',estimated_hours=7,technical_area='Backend',created_at=now,revision=3))
            db.execute(insert(squads).values(id=squad_id,project_id=project_id,name='Legacy squad',description='',technical_areas='["Backend"]',created_at=now,revision=2))
            db.execute(insert(old_members).values(id=member_id,project_id=project_id,squad_id=squad_id,name='Same name',role='Engineer',member_type=kind,active=True,
                weekly_capacity_hours=30 if kind=='human' else None,target_utilization=.8 if kind=='human' else None,
                availability='available' if kind=='ai' else None,max_concurrent_tasks=1 if kind=='ai' else None,
                future_execution_role='developer' if kind=='ai' else None,created_at=now,revision=4))
            db.execute(insert(old_skills).values(member_id=member_id,technical_area='Backend',proficiency=5))
            db.execute(insert(old_assignments).values(task_id=task_id,squad_id=squad_id,assignee_id=member_id,created_at=now))
            identities.append(dict(project_id=project_id,task_id=task_id,squad_id=squad_id,member_id=member_id))
    yield engine,identities
    engine.dispose()
    if schema:
        with root_engine.begin() as db: db.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
        root_engine.dispose()


def test_migration_preserves_ids_skills_ownership_duplicate_names_and_is_idempotent(legacy):
    engine,identities=legacy
    planning=PlanningStore(engine)
    teams=TeamStore(planning)
    global_data=teams.workspace_snapshot()
    assert len(global_data['members'])==3 and len(global_data['memberships'])==3
    assert {str(member.id) for member in global_data['members']}=={item['member_id'] for item in identities}
    assert all(member.name=='Same name' and member.revision==4 and member.skills[0].proficiency==5 for member in global_data['members'])
    for item in identities:
        task=planning.task(item['task_id'])
        assert str(task.assignee_id)==item['member_id'] and str(task.squad_id)==item['squad_id'] and task.revision==3
        assert teams.squad(item['squad_id']).revision==2
        snapshot=teams.snapshot(item['project_id'])
        assert len(snapshot['memberships'])==1 and snapshot['memberships'][0].active
    assert inspect(engine).has_table('team_members') and inspect(engine).has_table('team_member_skills')
    assert any(fk['referred_table']=='workspace_members' for fk in inspect(engine).get_foreign_keys('engineering_task_assignments'))
    # A later workspace edit must not be overwritten by the retained legacy data.
    from autonomous_engineering.domain.teams import MemberEdit
    member=global_data['members'][0]
    teams.save_workspace_member(MemberEdit.model_validate({**member.model_dump(exclude={'id','created_at'}),'name':'Edited after migration'}),member.id)
    before=teams.workspace_snapshot()
    PlanningStore(engine);PlanningStore(engine)
    assert teams.workspace_snapshot()==before
    with engine.connect() as db: assert len(list(db.execute(select(migrations))))==1


def test_failed_migration_rolls_back_and_can_retry(legacy, monkeypatch):
    engine, identities = legacy
    from autonomous_engineering.infrastructure import team_migrations
    original = team_migrations._retarget_assignments
    def fail_after_copy(db):
        raise RuntimeError('Injected migration interruption')
    monkeypatch.setattr(team_migrations, '_retarget_assignments', fail_after_copy)
    with pytest.raises(RuntimeError, match='Injected migration interruption'):
        PlanningStore(engine)
    with engine.connect() as db:
        assert {row[0] for row in db.execute(select(assignments.c.task_id))} == {item['task_id'] for item in identities}
        if inspect(db).has_table('workspace_members'):
            assert db.execute(select(members.c.id)).all() == []
        if inspect(db).has_table('team_schema_migrations'):
            assert db.execute(select(migrations)).all() == []
    monkeypatch.setattr(team_migrations, '_retarget_assignments', original)
    PlanningStore(engine)
    assert len(TeamStore(PlanningStore(engine)).workspace_snapshot()['members']) == 3
