"""Draft-only storage, distinct from actionable engineering tasks."""
import json
from sqlalchemy import Column, Integer, String, Text, Table, ForeignKey, insert, select, delete
from autonomous_engineering.infrastructure.task_store import metadata
from autonomous_engineering.domain.base import utc_now
from autonomous_engineering.domain.product_planning import ProductPlanDraft

drafts = Table('product_plan_drafts', metadata,
    Column('plan_id', String(36), ForeignKey('product_goals.id'), primary_key=True),
    Column('revision', Integer, nullable=False), Column('basis', Text, nullable=False),
    Column('approved_at', String(40)), Column('materialization', Text))
draft_epics = Table('product_plan_draft_epics', metadata,
    Column('plan_id', String(36), ForeignKey('product_plan_drafts.plan_id'), primary_key=True),
    Column('ref', String(20), primary_key=True), Column('position', Integer, nullable=False),
    Column('title', String(200), nullable=False), Column('description', Text, nullable=False))
draft_tasks = Table('product_plan_draft_tasks', metadata,
    Column('plan_id', String(36), ForeignKey('product_plan_drafts.plan_id'), primary_key=True),
    Column('ref', String(20), primary_key=True), Column('position', Integer, nullable=False),
    Column('data', Text, nullable=False))
draft_dependencies = Table('product_plan_draft_dependencies', metadata,
    Column('plan_id', String(36), ForeignKey('product_plan_drafts.plan_id'), primary_key=True),
    Column('task_ref', String(20), primary_key=True), Column('depends_on_ref', String(20), primary_key=True))
draft_criteria = Table('product_plan_draft_criteria', metadata,
    Column('plan_id', String(36), ForeignKey('product_plan_drafts.plan_id'), primary_key=True),
    Column('task_ref', String(20), primary_key=True), Column('position', Integer, primary_key=True),
    Column('description', Text, nullable=False))
versions = Table('product_plan_draft_versions', metadata,
    Column('plan_id', String(36), ForeignKey('product_plan_drafts.plan_id'), primary_key=True),
    Column('revision', Integer, primary_key=True), Column('created_at', String(40), nullable=False),
    Column('data', Text, nullable=False))
DRAFT_TABLES = [drafts, draft_epics, draft_tasks, draft_dependencies, draft_criteria, versions]


def write_draft(db, goal_id, draft, revision):
    from autonomous_engineering.infrastructure.planning_store import goals
    for table in [draft_dependencies, draft_criteria, draft_tasks, draft_epics]:
        db.execute(delete(table).where(table.c.plan_id == goal_id))
    for position, epic in enumerate(draft.epics):
        db.execute(insert(draft_epics).values(plan_id=goal_id, position=position, **epic.model_dump()))
    for position, task in enumerate(draft.tasks):
        db.execute(insert(draft_tasks).values(plan_id=goal_id, ref=task.ref, position=position,
            data=task.model_dump_json(exclude={'dependencies', 'acceptance_criteria'})))
        for ref in task.dependencies:
            db.execute(insert(draft_dependencies).values(plan_id=goal_id, task_ref=task.ref, depends_on_ref=ref))
        for index, criterion in enumerate(task.acceptance_criteria):
            db.execute(insert(draft_criteria).values(plan_id=goal_id, task_ref=task.ref, position=index, description=criterion.description))
    db.execute(goals.update().where(goals.c.id == goal_id).values(title=draft.title, summary=draft.summary, assumptions=json.dumps(draft.assumptions)))
    db.execute(insert(versions).values(plan_id=goal_id, revision=revision, created_at=utc_now().isoformat(), data=draft.model_dump_json()))


def read_draft(db, goal):
    identity = goal['id']
    epics = [dict(ref=row['ref'], title=row['title'], description=row['description']) for row in db.execute(
        select(draft_epics).where(draft_epics.c.plan_id == identity).order_by(draft_epics.c.position)).mappings()]
    tasks = []
    for row in db.execute(select(draft_tasks).where(draft_tasks.c.plan_id == identity).order_by(draft_tasks.c.position)).mappings():
        data = json.loads(row['data'])
        data['dependencies'] = list(db.execute(select(draft_dependencies.c.depends_on_ref).where(
            draft_dependencies.c.plan_id == identity, draft_dependencies.c.task_ref == row['ref']).order_by(draft_dependencies.c.depends_on_ref)).scalars())
        data['acceptance_criteria'] = [dict(description=value) for value in db.execute(select(draft_criteria.c.description).where(
            draft_criteria.c.plan_id == identity, draft_criteria.c.task_ref == row['ref']).order_by(draft_criteria.c.position)).scalars()]
        tasks.append(data)
    return ProductPlanDraft(title=goal['title'], summary=goal['summary'], assumptions=json.loads(goal['assumptions']), epics=epics, tasks=tasks)
