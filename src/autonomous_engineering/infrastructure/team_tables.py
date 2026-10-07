"""Additive, portable team schema and project-level mutation fencing."""
from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Table, Text, update, select
from autonomous_engineering.infrastructure.task_store import metadata

squads = Table('team_squads', metadata,
    Column('id', String(36), primary_key=True),
    Column('project_id', String(36), ForeignKey('projects.id'), nullable=False, index=True),
    Column('name', String(200), nullable=False), Column('description', Text, nullable=False),
    Column('technical_areas', Text, nullable=False), Column('created_at', String(40), nullable=False),
    Column('revision', Integer, nullable=False))
members = Table('team_members', metadata,
    Column('id', String(36), primary_key=True),
    Column('project_id', String(36), ForeignKey('projects.id'), nullable=False, index=True),
    Column('squad_id', String(36), ForeignKey('team_squads.id'), nullable=False),
    Column('name', String(200), nullable=False), Column('role', String(200), nullable=False),
    Column('member_type', String(10), nullable=False), Column('active', Boolean, nullable=False),
    Column('weekly_capacity_hours', Float), Column('target_utilization', Float),
    Column('availability', String(20)), Column('max_concurrent_tasks', Integer),
    Column('future_execution_role', String(20)), Column('created_at', String(40), nullable=False),
    Column('revision', Integer, nullable=False))
skills = Table('team_member_skills', metadata,
    Column('member_id', String(36), ForeignKey('team_members.id'), primary_key=True),
    Column('technical_area', String(20), primary_key=True), Column('proficiency', Integer, nullable=False))
assignments = Table('engineering_task_assignments', metadata,
    Column('task_id', String(36), ForeignKey('engineering_tasks.id'), primary_key=True),
    Column('squad_id', String(36), ForeignKey('team_squads.id'), nullable=False),
    Column('assignee_id', String(36), ForeignKey('team_members.id')),
    Column('created_at', String(40), nullable=False))
team_revisions = Table('team_project_revisions', metadata,
    Column('project_id', String(36), ForeignKey('projects.id'), primary_key=True),
    Column('revision', Integer, nullable=False))
TEAM_TABLES = [squads, members, skills, assignments, team_revisions]


def lock_project(db, project_id, expected_revision=None):
    """SQL row update serializes load checks and fences suggestion application."""
    from autonomous_engineering.infrastructure.planning_store import PlanningConflict
    if db.dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    db.execute(insert(team_revisions).values(project_id=str(project_id), revision=0)
        .on_conflict_do_nothing(index_elements=['project_id']))
    query = update(team_revisions).where(team_revisions.c.project_id == str(project_id))
    if expected_revision is not None:
        query = query.where(team_revisions.c.revision == expected_revision)
    if db.execute(query.values(revision=team_revisions.c.revision + 1)).rowcount != 1:
        raise PlanningConflict('Team or tasks changed. Refresh recommendations before applying them.')
    return db.execute(select(team_revisions.c.revision).where(team_revisions.c.project_id == str(project_id))).scalar_one()
