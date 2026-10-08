"""Additive preview history, deliberately separate from engineering job leases."""
from sqlalchemy import MetaData, Table, Column, String, Text, Integer, Float, ForeignKey, update
from autonomous_engineering.infrastructure.task_store import projects
from autonomous_engineering.infrastructure.planning_store import engineering_tasks
from autonomous_engineering.infrastructure.task_execution_tables import execution_links

preview_metadata = MetaData()
preview_profiles = Table('preview_profiles',preview_metadata,
    Column('id',String(36),primary_key=True),Column('project_id',String(36),ForeignKey(projects.c.id),nullable=False,unique=True),
    Column('data',Text,nullable=False),Column('revision',Integer,nullable=False),Column('created_at',String(40),nullable=False))
execution_previews = Table('execution_previews',preview_metadata,
    Column('id',String(36),primary_key=True),
    Column('engineering_task_id',String(36),ForeignKey(engineering_tasks.c.id),nullable=False,index=True),
    Column('execution_task_id',String(36),ForeignKey(execution_links.c.execution_task_id),nullable=False,index=True),
    Column('run_id',String(36),nullable=False),Column('profile_id',String(36),ForeignKey(preview_profiles.c.id),nullable=False),
    Column('profile_snapshot',Text,nullable=False),Column('status',String(24),nullable=False),
    Column('active_execution_id',String(36),unique=True),
    Column('container_id',String(80)),Column('host_port',Integer),Column('source_digest',String(64)),
    Column('created_at',String(40),nullable=False),Column('started_at',String(40)),Column('ready_at',String(40)),
    Column('stopped_at',String(40)),Column('expires_at',String(40),nullable=False),Column('failure_reason',Text),
    Column('logs',Text,nullable=False),Column('owner',String(36)),Column('lease',Float),Column('stop_reason',String(24)))

def lock_previews(db):
    """Share the existing global fence without invalidating Team recommendations.

    Preview resources never change organizational or AI runtime capacity.
    """
    from autonomous_engineering.infrastructure.team_tables import workspace_state
    db.execute(update(workspace_state).where(workspace_state.c.id=='local').values(revision=workspace_state.c.revision))

def stop_execution_previews(db, execution_id, reason='stopped'):
    from sqlalchemy import update
    from autonomous_engineering.domain.previews import ACTIVE_PREVIEWS
    db.execute(update(execution_previews).where(execution_previews.c.execution_task_id==str(execution_id),
        execution_previews.c.status.in_(ACTIVE_PREVIEWS)).values(status='stopping',stop_reason=reason))
