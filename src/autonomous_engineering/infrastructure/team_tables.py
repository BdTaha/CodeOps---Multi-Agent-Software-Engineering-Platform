"""Workspace identities, project memberships, and global resource fencing."""
from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Table, Text, UniqueConstraint, update, select
from autonomous_engineering.infrastructure.task_store import metadata

squads = Table('team_squads', metadata,
    Column('id', String(36), primary_key=True),
    Column('project_id', String(36), ForeignKey('projects.id'), nullable=False, index=True),
    Column('name', String(200), nullable=False), Column('description', Text, nullable=False),
    Column('technical_areas', Text, nullable=False), Column('created_at', String(40), nullable=False),
    Column('revision', Integer, nullable=False))
members = Table('workspace_members', metadata,
    Column('id', String(36), primary_key=True),
    Column('name', String(200), nullable=False), Column('role', String(200), nullable=False),
    Column('member_type', String(10), nullable=False), Column('active', Boolean, nullable=False),
    Column('weekly_capacity_hours', Float), Column('target_utilization', Float),
    Column('availability', String(20)), Column('max_concurrent_executions', Integer),
    Column('future_execution_role', String(20)), Column('created_at', String(40), nullable=False),
    Column('revision', Integer, nullable=False))
skills = Table('workspace_member_skills', metadata,
    Column('member_id', String(36), ForeignKey('workspace_members.id'), primary_key=True),
    Column('technical_area', String(20), primary_key=True), Column('proficiency', Integer, nullable=False))
memberships = Table('project_memberships', metadata,
    Column('id', String(36), primary_key=True),
    Column('project_id', String(36), ForeignKey('projects.id'), nullable=False, index=True),
    Column('member_id', String(36), ForeignKey('workspace_members.id'), nullable=False),
    Column('squad_id', String(36), ForeignKey('team_squads.id'), nullable=False),
    Column('active', Boolean, nullable=False), Column('created_at', String(40), nullable=False),
    Column('revision', Integer, nullable=False),
    UniqueConstraint('project_id', 'member_id', name='uq_project_workspace_member'))
assignments = Table('engineering_task_assignments', metadata,
    Column('task_id', String(36), ForeignKey('engineering_tasks.id'), primary_key=True),
    Column('squad_id', String(36), ForeignKey('team_squads.id'), nullable=False),
    Column('assignee_id', String(36), ForeignKey('workspace_members.id')),
    Column('created_at', String(40), nullable=False))
team_revisions = Table('team_project_revisions', metadata,
    Column('project_id', String(36), ForeignKey('projects.id'), primary_key=True),
    Column('revision', Integer, nullable=False))
workspace_state = Table('workspace_team_state', metadata,
    Column('id', String(20), primary_key=True), Column('revision', Integer, nullable=False))
migrations = Table('team_schema_migrations', metadata,
    Column('version', String(60), primary_key=True), Column('completed_at', String(40), nullable=False))
TEAM_TABLES = [squads, members, skills, memberships, assignments, team_revisions, workspace_state, migrations]


def _insert(db):
    if db.dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert


def lock_workspace(db, expected_revision=None):
    """All resource mutations take this lock first, including task status changes."""
    from autonomous_engineering.infrastructure.planning_store import PlanningConflict
    db.execute(_insert(db)(workspace_state).values(id='local', revision=0).on_conflict_do_nothing(index_elements=['id']))
    query = update(workspace_state).where(workspace_state.c.id == 'local')
    if expected_revision is not None:
        query = query.where(workspace_state.c.revision == expected_revision)
    if db.execute(query.values(revision=workspace_state.c.revision + 1)).rowcount != 1:
        raise PlanningConflict('Workspace resources or assigned work changed. Refresh recommendations.')
    return db.execute(select(workspace_state.c.revision).where(workspace_state.c.id == 'local')).scalar_one()


def lock_project(db, project_id, expected_revision=None, expected_workspace_revision=None):
    from autonomous_engineering.infrastructure.planning_store import PlanningConflict
    lock_workspace(db, expected_workspace_revision)
    db.execute(_insert(db)(team_revisions).values(project_id=str(project_id), revision=0).on_conflict_do_nothing(index_elements=['project_id']))
    query = update(team_revisions).where(team_revisions.c.project_id == str(project_id))
    if expected_revision is not None:
        query = query.where(team_revisions.c.revision == expected_revision)
    if db.execute(query.values(revision=team_revisions.c.revision + 1)).rowcount != 1:
        raise PlanningConflict('Team or tasks changed. Refresh recommendations before applying them.')
    return db.execute(select(team_revisions.c.revision).where(team_revisions.c.project_id == str(project_id))).scalar_one()
