"""Additive history schema; runtime phase stays canonical in tasks."""
from sqlalchemy import MetaData, Table, Column, String, Text, ForeignKey, select, update, inspect
from autonomous_engineering.infrastructure.task_store import tasks
from autonomous_engineering.infrastructure.planning_store import engineering_tasks, PlanningConflict
from autonomous_engineering.infrastructure.team_tables import members, lock_project
from autonomous_engineering.domain.task_executions import ACTIVE_EXECUTION_PHASES

# Separate metadata keeps legacy schema migration independent of this new table.
execution_links = Table('engineering_task_executions', MetaData(),
    Column('execution_task_id', String(36), ForeignKey(tasks.c.id), primary_key=True),
    Column('run_id', String(36), nullable=False, unique=True),
    Column('engineering_task_id', String(36), ForeignKey(engineering_tasks.c.id), nullable=False, index=True),
    Column('ai_member_id', String(36), ForeignKey(members.c.id), nullable=False, index=True),
    Column('parent_execution_task_id', String(36), ForeignKey(tasks.c.id)),
    Column('created_at', String(40), nullable=False),
    Column('review_state', String(24), nullable=False),
    Column('reviewed_at', String(40)), Column('feedback', Text))


def runtime_link(db, execution_id):
    if not inspect(db).has_table(execution_links.name):
        return None
    return db.execute(select(execution_links).where(execution_links.c.execution_task_id == str(execution_id))).mappings().first()


def fence_execution(db, execution_id):
    link = runtime_link(db, execution_id)
    if link:
        project_id = db.execute(select(engineering_tasks.c.project_id).where(engineering_tasks.c.id == link['engineering_task_id'])).scalar_one()
        lock_project(db, project_id)
        # Reload after taking the global lock: acceptance and retries share it.
        link = runtime_link(db, execution_id)
    return link


def active_for_task(db, task_id):
    return db.execute(select(execution_links.c.execution_task_id).join(tasks, tasks.c.id == execution_links.c.execution_task_id)
        .where(execution_links.c.engineering_task_id == str(task_id), tasks.c.phase.in_(ACTIVE_EXECUTION_PHASES))).first() is not None


def synchronize_completion(db, link, phase):
    if link and phase in {'failed','cancelled'}:
        from autonomous_engineering.infrastructure.acceptance_tables import evidence_runs
        db.execute(update(evidence_runs).where(evidence_runs.c.execution_task_id==link['execution_task_id'],evidence_runs.c.state=='waiting')
            .values(state='not_generated'))
    if link and phase == 'succeeded' and link['review_state'] == 'pending':
        from autonomous_engineering.infrastructure.acceptance_store import queue_evidence
        queue_evidence(db, link['execution_task_id'])
        db.execute(update(engineering_tasks).where(engineering_tasks.c.id == link['engineering_task_id'],
            engineering_tasks.c.execution_run_id == link['run_id'], engineering_tasks.c.status == 'in_progress')
            .values(status='review', revision=engineering_tasks.c.revision + 1))


def delivery_allowed(db, execution_id):
    link = runtime_link(db, execution_id)
    if link and (link['review_state'] != 'accepted' or not db.execute(select(engineering_tasks.c.id).where(
            engineering_tasks.c.id == link['engineering_task_id'], engineering_tasks.c.execution_run_id == link['run_id'],
            engineering_tasks.c.status == 'done')).first()):
        raise PlanningConflict('Accept the latest linked result on its EngineeringTask before delivery.')
