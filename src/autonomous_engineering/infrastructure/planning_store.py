"""Normalized product planning tables alongside the existing execution store."""
import json
import time
from uuid import uuid4

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Table, Text, UniqueConstraint, insert, select, update, func
from sqlalchemy.exc import IntegrityError

from autonomous_engineering.domain.base import utc_now
from autonomous_engineering.domain.product_planning import (
    EngineeringTask, Epic, PlanRecord, ProductPlanDraft, ProjectGoal, ProjectPlan,
)
from autonomous_engineering.infrastructure.task_store import LostLease, metadata, projects, events

goals = Table('product_goals', metadata,
    Column('id', String(36), primary_key=True),
    Column('project_id', String(36), ForeignKey('projects.id'), nullable=False, index=True),
    Column('goal', Text, nullable=False), Column('created_at', String(40), nullable=False),
    Column('status', String(20), nullable=False),
    # A unique non-null project blocks concurrent plans; NULL permits history.
    Column('active_project', String(36), unique=True),
    Column('owner', String(36)), Column('lease', Float),
    Column('revision', Integer, nullable=False), Column('attempts', Integer, nullable=False),
    Column('error', Text), Column('model', String(200)),
    Column('title', String(200)), Column('summary', Text), Column('assumptions', Text))
epics = Table('product_epics', metadata,
    Column('id', String(36), primary_key=True), Column('plan_id', String(36), ForeignKey('product_goals.id'), nullable=False),
    Column('position', Integer, nullable=False), Column('title', String(200), nullable=False), Column('description', Text, nullable=False))
engineering_tasks = Table('engineering_tasks', metadata,
    Column('id', String(36), primary_key=True), Column('project_id', String(36), ForeignKey('projects.id'), nullable=False),
    Column('plan_id', String(36), ForeignKey('product_goals.id'), nullable=False, index=True),
    Column('epic_id', String(36), ForeignKey('product_epics.id'), nullable=False),
    Column('number', Integer, nullable=False), Column('title', String(200), nullable=False),
    Column('description', Text, nullable=False), Column('status', String(20), nullable=False),
    Column('priority', String(20), nullable=False), Column('estimated_hours', Float, nullable=False),
    Column('technical_area', String(20), nullable=False), Column('created_at', String(40), nullable=False),
    Column('revision', Integer, nullable=False), Column('execution_run_id', String(36)),
    UniqueConstraint('project_id', 'number', name='uq_engineering_project_number'))
dependencies = Table('engineering_task_dependencies', metadata,
    Column('task_id', String(36), ForeignKey('engineering_tasks.id'), primary_key=True),
    Column('depends_on_id', String(36), ForeignKey('engineering_tasks.id'), primary_key=True))
criteria = Table('engineering_acceptance_criteria', metadata,
    Column('task_id', String(36), ForeignKey('engineering_tasks.id'), primary_key=True),
    Column('position', Integer, primary_key=True), Column('description', Text, nullable=False),
    Column('id', String(36), unique=True))


class PlanningConflict(RuntimeError):
    pass


class PlanningStore:
    def __init__(self, engine):
        self.engine = engine
        metadata.create_all(engine, tables=[goals, epics, engineering_tasks, dependencies, criteria])
        from autonomous_engineering.infrastructure.team_migrations import initialize_team_schema
        initialize_team_schema(engine)

    def project(self, project_id):
        with self.engine.connect() as db:
            row = db.execute(select(projects.c.data).where(projects.c.id == str(project_id))).scalar_one_or_none()
            return json.loads(row) if row else None

    def enqueue(self, project_id, goal):
        from autonomous_engineering.infrastructure.team_tables import lock_project
        goal_id = str(uuid4())
        try:
            with self.engine.begin() as db:
                lock_project(db, project_id)
                db.execute(insert(goals).values(id=goal_id, project_id=str(project_id), goal=goal,
                    created_at=utc_now().isoformat(), status='queued', active_project=str(project_id), revision=0, attempts=0))
        except IntegrityError as exc:
            raise PlanningConflict('This project already has a plan being generated. Wait for it to finish.') from exc
        return self.get(goal_id)

    def latest(self, project_id):
        with self.engine.connect() as db:
            goal_id = db.execute(select(goals.c.id).where(goals.c.project_id == str(project_id))
                .order_by(goals.c.created_at.desc(), goals.c.id.desc()).limit(1)).scalar_one_or_none()
        return self.get(goal_id) if goal_id else None

    def _task(self, db, row):
        from autonomous_engineering.infrastructure.team_tables import assignments
        values = dict(row)
        assignment = db.execute(select(assignments).where(assignments.c.task_id == values['id'])).mappings().first()
        values['squad_id'] = assignment['squad_id'] if assignment else None
        values['assignee_id'] = assignment['assignee_id'] if assignment else None
        values['key'] = 'CO-' + str(values.pop('number'))
        values['dependencies'] = [{'task_id': ref} for ref in db.execute(select(dependencies.c.depends_on_id)
            .where(dependencies.c.task_id == values['id']).order_by(dependencies.c.depends_on_id)).scalars()]
        values['acceptance_criteria'] = [dict(item) for item in db.execute(select(criteria.c.id, criteria.c.description)
            .where(criteria.c.task_id == values['id']).order_by(criteria.c.position)).mappings()]
        return EngineeringTask.model_validate(values)

    def task(self, task_id):
        with self.engine.connect() as db:
            row = db.execute(select(engineering_tasks).where(engineering_tasks.c.id == str(task_id))).mappings().first()
            return self._task(db, row) if row else None

    def get(self, goal_id):
        with self.engine.connect() as db:
            row = db.execute(select(goals).where(goals.c.id == str(goal_id))).mappings().first()
            if row is None:
                return None
            goal = ProjectGoal(id=row['id'], project_id=row['project_id'], goal=row['goal'], created_at=row['created_at'])
            plan = None
            if row['status'] == 'ready':
                epic_list = tuple(Epic.model_validate({key: value for key, value in item.items() if key != 'position'})
                    for item in db.execute(select(epics).where(epics.c.plan_id == row['id']).order_by(epics.c.position)).mappings())
                task_list = tuple(self._task(db, item) for item in db.execute(select(engineering_tasks)
                    .where(engineering_tasks.c.plan_id == row['id']).order_by(engineering_tasks.c.number)).mappings())
                plan = ProjectPlan(id=row['id'], project_id=row['project_id'], title=row['title'], summary=row['summary'],
                    assumptions=json.loads(row['assumptions']), epics=epic_list, tasks=task_list,
                    estimated_hours=sum(task.estimated_hours for task in task_list))
            invocations = tuple(json.loads(data) for data in db.execute(select(events.c.data).where(
                events.c.task_id == row['id'], events.c.kind == 'model_invocation').order_by(events.c.id)).scalars())
            return PlanRecord(goal=goal, status=row['status'], plan=plan, attempts=row['attempts'], error=row['error'], model=row['model'], model_invocations=invocations)

    def claim(self, owner, lease_seconds):
        with self.engine.begin() as db:
            row = db.execute(select(goals).where(goals.c.status == 'queued').order_by(goals.c.created_at).limit(1)).mappings().first()
            if not row:
                return None
            claimed = db.execute(update(goals).where(goals.c.id == row['id'], goals.c.status == 'queued',
                goals.c.revision == row['revision']).values(status='generating', owner=owner,
                    lease=time.time() + lease_seconds, revision=row['revision'] + 1))
            return dict(row) if claimed.rowcount == 1 else None

    def heartbeat(self, goal_id, owner, seconds):
        with self.engine.begin() as db:
            result = db.execute(update(goals).where(goals.c.id == goal_id, goals.c.owner == owner,
                goals.c.status == 'generating', goals.c.lease > time.time()).values(lease=time.time() + seconds))
            return result.rowcount == 1

    def settle_interrupted(self):
        with self.engine.begin() as db:
            db.execute(update(goals).where(goals.c.status == 'generating', goals.c.lease < time.time()).values(
                status='failed', active_project=None, owner=None, lease=None,
                error='PLANNING_INTERRUPTED: Worker stopped during planning. Submit the goal again to retry.'))

    def fail(self, goal_id, owner, error, attempts, model):
        with self.engine.begin() as db:
            result = db.execute(update(goals).where(goals.c.id == goal_id, goals.c.owner == owner,
                goals.c.status == 'generating', goals.c.lease > time.time()).values(status='failed', error=error[:4000],
                    attempts=attempts, model=model, active_project=None, owner=None, lease=None))
            if result.rowcount != 1:
                raise LostLease('Product planning lease was lost.')

    def complete(self, goal_id, owner, draft: ProductPlanDraft, attempts, model):
        from autonomous_engineering.infrastructure.team_tables import lock_project
        draft = ProductPlanDraft.model_validate(draft)
        with self.engine.begin() as db:
            row = db.execute(select(goals).where(goals.c.id == goal_id)).mappings().one()
            lock_project(db, row['project_id'])
            result = db.execute(update(goals).where(goals.c.id == goal_id, goals.c.owner == owner,
                goals.c.status == 'generating', goals.c.lease > time.time()).values(status='ready', title=draft.title,
                    summary=draft.summary, assumptions=json.dumps(draft.assumptions), attempts=attempts, model=model,
                    active_project=None, owner=None, lease=None))
            if result.rowcount != 1:
                raise LostLease('Product planning lease was lost; no plan was saved.')
            epic_ids = {epic.ref: str(uuid4()) for epic in draft.epics}
            task_ids = {task.ref: str(uuid4()) for task in draft.tasks}
            number = db.execute(select(func.max(engineering_tasks.c.number))
                .where(engineering_tasks.c.project_id == row['project_id'])).scalar_one() or 0
            for position, epic in enumerate(draft.epics):
                db.execute(insert(epics).values(id=epic_ids[epic.ref], plan_id=goal_id, position=position,
                    title=epic.title, description=epic.description))
            for offset, task in enumerate(draft.tasks, 1):
                db.execute(insert(engineering_tasks).values(id=task_ids[task.ref], project_id=row['project_id'],
                    plan_id=goal_id, epic_id=epic_ids[task.epic_ref], number=number + offset,
                    title=task.title, description=task.description, status='backlog', priority=task.priority.value,
                    estimated_hours=task.estimated_hours, technical_area=task.technical_area.value,
                    created_at=utc_now().isoformat(), revision=0))
            for task in draft.tasks:
                for ref in task.dependencies:
                    db.execute(insert(dependencies).values(task_id=task_ids[task.ref], depends_on_id=task_ids[ref]))
                for position, criterion in enumerate(task.acceptance_criteria):
                    db.execute(insert(criteria).values(id=str(uuid4()), task_id=task_ids[task.ref], position=position, description=criterion.description))
        return self.get(goal_id)

    def set_status(self, task_id, status, revision):
        from autonomous_engineering.infrastructure.team_tables import lock_project
        with self.engine.begin() as db:
            project_id = db.execute(select(engineering_tasks.c.project_id).where(engineering_tasks.c.id == str(task_id))).scalar_one()
            lock_project(db, project_id)
            from autonomous_engineering.infrastructure.task_execution_tables import active_for_task, execution_links
            if active_for_task(db, task_id):
                raise PlanningConflict('An execution is active. Cancel it and wait for it to stop before changing task status.')
            if db.execute(select(execution_links.c.execution_task_id).where(execution_links.c.engineering_task_id == str(task_id))).first():
                raise PlanningConflict('Linked task status follows execution and human acceptance. Use its execution review actions.')
            result = db.execute(update(engineering_tasks).where(engineering_tasks.c.id == str(task_id),
                engineering_tasks.c.revision == revision).values(status=status.value, revision=revision + 1))
            if result.rowcount != 1:
                raise PlanningConflict('Task changed in another window. Reload its current status and try again.')
        return self.task(task_id)
