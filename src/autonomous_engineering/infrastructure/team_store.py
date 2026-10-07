"""Persisted teams, assignments and atomic, capacity-safe suggestion application."""
import json
from uuid import uuid4
from sqlalchemy import delete, insert, select, update

from autonomous_engineering.domain.base import utc_now
from autonomous_engineering.domain.teams import Squad, TeamMember
from autonomous_engineering.domain.product_planning import EngineeringTask
from autonomous_engineering.infrastructure.planning_store import PlanningConflict, engineering_tasks, goals
from autonomous_engineering.infrastructure.team_tables import squads, members, skills, assignments, team_revisions, lock_project
from autonomous_engineering.application.assignment_recommendations import capacities, recommend, assignment_warnings, dependency_warnings


class TeamNotFound(ValueError):
    pass


class AssignmentWarnings(ValueError):
    def __init__(self, warnings):
        self.warnings = warnings
        super().__init__('Review assignment warnings and explicitly allow them to continue.')


class TeamStore:
    def __init__(self, planning):
        self.planning = planning
        self.engine = planning.engine

    def _squad(self, row):
        return Squad.model_validate({**dict(row), 'technical_areas': json.loads(row['technical_areas'])})

    def _member(self, db, row):
        configured = [dict(item) for item in db.execute(select(skills.c.technical_area, skills.c.proficiency)
            .where(skills.c.member_id == row['id']).order_by(skills.c.technical_area)).mappings()]
        return TeamMember.model_validate({**dict(row), 'skills': configured})

    def squad(self, squad_id):
        with self.engine.connect() as db:
            row = db.execute(select(squads).where(squads.c.id == str(squad_id))).mappings().first()
            return self._squad(row) if row else None

    def member(self, member_id):
        with self.engine.connect() as db:
            row = db.execute(select(members).where(members.c.id == str(member_id))).mappings().first()
            return self._member(db, row) if row else None

    def _snapshot(self, db, project_id):
        squad_list = [self._squad(row) for row in db.execute(select(squads).where(squads.c.project_id == str(project_id)).order_by(squads.c.created_at, squads.c.id)).mappings()]
        member_list = [self._member(db, row) for row in db.execute(select(members).where(members.c.project_id == str(project_id)).order_by(members.c.created_at, members.c.id)).mappings()]
        tasks = [self.planning._task(db, row) for row in db.execute(select(engineering_tasks).where(engineering_tasks.c.project_id == str(project_id)).order_by(engineering_tasks.c.number)).mappings()]
        revision = db.execute(select(team_revisions.c.revision).where(team_revisions.c.project_id == str(project_id))).scalar_one_or_none() or 0
        latest = db.execute(select(goals.c.id, goals.c.status).where(goals.c.project_id == str(project_id))
            .order_by(goals.c.created_at.desc(), goals.c.id.desc()).limit(1)).mappings().first()
        return dict(squads=squad_list, members=member_list, tasks=tasks, project_revision=revision,
            capacities=list(capacities(member_list, tasks).values()),
            current_plan_id=latest['id'] if latest and latest['status'] == 'ready' else None)

    def snapshot(self, project_id):
        # A read transaction sees a coherent resource snapshot on both databases.
        with self.engine.connect() as db:
            if db.dialect.name == 'postgresql':
                db = db.execution_options(isolation_level='REPEATABLE READ')
            with db.begin():
                if db.dialect.name == 'sqlite':
                    # sqlite3's legacy transaction mode does not begin on SELECT.
                    db.exec_driver_sql('BEGIN')
                return self._snapshot(db, project_id)

    def save_squad(self, project_id, body, squad_id=None):
        identity = str(squad_id or uuid4())
        with self.engine.begin() as db:
            lock_project(db, project_id)
            values = body.model_dump(mode='json', exclude={'revision'})
            values['technical_areas'] = json.dumps(values['technical_areas'])
            if squad_id:
                result = db.execute(update(squads).where(squads.c.id == identity, squads.c.project_id == str(project_id),
                    squads.c.revision == body.revision).values(**values, revision=body.revision + 1))
                if result.rowcount != 1: raise PlanningConflict('Squad changed. Refresh and try again.')
            else:
                db.execute(insert(squads).values(**values, id=identity, project_id=str(project_id), revision=0, created_at=utc_now().isoformat()))
        return self.squad(identity)

    def save_member(self, project_id, body, member_id=None):
        identity = str(member_id or uuid4())
        with self.engine.begin() as db:
            lock_project(db, project_id)
            squad = db.execute(select(squads).where(squads.c.id == str(body.squad_id), squads.c.project_id == str(project_id))).first()
            if squad is None: raise TeamNotFound('Squad does not belong to this project.')
            values = body.model_dump(mode='json', exclude={'revision', 'skills'})
            if member_id:
                existing = db.execute(select(members).where(members.c.id == identity)).mappings().one()
                if body.member_type != existing['member_type']:
                    raise ValueError('Member type cannot change. Create a separate organizational identity.')
                result = db.execute(update(members).where(members.c.id == identity, members.c.project_id == str(project_id),
                    members.c.revision == body.revision).values(**values, revision=body.revision + 1))
                if result.rowcount != 1: raise PlanningConflict('Member changed. Refresh and try again.')
                # Keep existing primary-assignee squads consistent when moving a member.
                affected = select(assignments.c.task_id).where(assignments.c.assignee_id == identity)
                db.execute(update(engineering_tasks).where(engineering_tasks.c.id.in_(affected)).values(revision=engineering_tasks.c.revision + 1))
                db.execute(update(assignments).where(assignments.c.assignee_id == identity).values(squad_id=str(body.squad_id)))
                db.execute(delete(skills).where(skills.c.member_id == identity))
            else:
                db.execute(insert(members).values(**values, id=identity, project_id=str(project_id), revision=0, created_at=utc_now().isoformat()))
            for skill in body.skills:
                db.execute(insert(skills).values(member_id=identity, technical_area=skill.technical_area.value, proficiency=skill.proficiency))
        return self.member(identity)

    def _write_assignment(self, db, task, squad_id, assignee_id):
        changed = db.execute(update(engineering_tasks).where(engineering_tasks.c.id == str(task.id),
            engineering_tasks.c.revision == task.revision).values(revision=task.revision + 1))
        if changed.rowcount != 1: raise PlanningConflict('Task changed. Refresh and try again.')
        db.execute(delete(assignments).where(assignments.c.task_id == str(task.id)))
        if squad_id is not None:
            db.execute(insert(assignments).values(task_id=str(task.id), squad_id=str(squad_id),
                assignee_id=str(assignee_id) if assignee_id else None, created_at=utc_now().isoformat()))

    def assign(self, task_id, body=None, revision=None):
        task = self.planning.task(task_id)
        if task is None: raise TeamNotFound('Engineering task not found.')
        with self.engine.begin() as db:
            lock_project(db, task.project_id)
            snapshot = self._snapshot(db, task.project_id)
            task = next(item for item in snapshot['tasks'] if item.id == task.id)
            expected = body.revision if body else revision
            if task.revision != expected: raise PlanningConflict('Task changed. Refresh and try again.')
            warnings = []
            squad_id, member_id = None, None
            if body:
                squad_id, member_id = body.squad_id, body.assignee_id
                if member_id:
                    member = next((item for item in snapshot['members'] if item.id == member_id), None)
                    if member is None: raise TeamNotFound('Member does not belong to this project.')
                    if squad_id and squad_id != member.squad_id: raise ValueError('Assignee must belong to the selected squad.')
                    squad_id = member.squad_id
                    squad = next(item for item in snapshot['squads'] if item.id == squad_id)
                    warnings = assignment_warnings(task, member, squad, capacities(snapshot['members'], snapshot['tasks'])[member.id], snapshot['tasks'])
                elif not any(item.id == squad_id for item in snapshot['squads']):
                    raise TeamNotFound('Squad does not belong to this project.')
                else:
                    warnings = dependency_warnings(task, snapshot['tasks'])
                if warnings and not body.override_warnings: raise AssignmentWarnings(warnings)
            self._write_assignment(db, task, squad_id, member_id)
        return dict(task=self.planning.task(task_id), warnings=warnings)

    def recommendations(self, task_id):
        task = self.planning.task(task_id)
        if task is None: raise TeamNotFound('Engineering task not found.')
        snapshot = self.snapshot(task.project_id)
        task = next(item for item in snapshot['tasks'] if item.id == task.id)
        return dict(recommendations=recommend(task, snapshot['members'], snapshot['squads'], snapshot['tasks']),
            warnings=dependency_warnings(task, snapshot['tasks']), project_revision=snapshot['project_revision'])

    def suggested_plan(self, project_id):
        snapshot = self.snapshot(project_id)
        current_plan = snapshot['current_plan_id']
        return self._suggest(snapshot, current_plan)

    def _suggest(self, snapshot, plan_id):
        projected = list(snapshot['tasks'])
        suggestions, unfilled = [], []
        priorities = {'urgent': 0, 'high': 1, 'medium': 2, 'low': 3}
        eligible = sorted((task for task in projected if str(task.plan_id) == plan_id and task.assignee_id is None and task.status != 'done'),
            key=lambda task: (priorities[task.priority], int(task.key.split('-')[1])))
        for task in eligible:
            options = recommend(task, snapshot['members'], snapshot['squads'], projected)
            candidate = next((option for option in options if option.fits_capacity and task.technical_area in next(s.technical_areas for s in snapshot['squads'] if s.id == option.squad_id)), None)
            if not candidate:
                unfilled.append(dict(task_id=task.id, key=task.key, reason='No matching member with sufficient planned capacity in an appropriate squad.'))
                continue
            suggestions.append(dict(task_id=task.id, key=task.key, title=task.title, revision=task.revision,
                assignee_id=candidate.member_id, squad_id=candidate.squad_id, reasons=candidate.reasons, warnings=candidate.warnings))
            projected = [EngineeringTask.model_validate({**item.model_dump(), 'assignee_id': candidate.member_id, 'squad_id': candidate.squad_id}) if item.id == task.id else item for item in projected]
        return dict(project_revision=snapshot['project_revision'], suggestions=suggestions, unfilled=unfilled)

    def apply(self, project_id, body):
        with self.engine.begin() as db:
            lock_project(db, project_id, body.project_revision)
            snapshot = self._snapshot(db, project_id)
            plan_id = snapshot['current_plan_id']
            projected = list(snapshot['tasks'])
            for selection in body.assignments:
                task = next((task for task in projected if task.id == selection.task_id and str(task.plan_id) == plan_id), None)
                if task is None: raise TeamNotFound('Task is not in this project\'s current plan.')
                if task.revision != selection.revision or task.assignee_id is not None:
                    raise PlanningConflict('An assignment changed. Refresh recommendations.')
                candidate = next((item for item in recommend(task, snapshot['members'], snapshot['squads'], projected)
                    if item.member_id == selection.assignee_id and item.fits_capacity), None)
                if candidate is None or task.technical_area not in next(s.technical_areas for s in snapshot['squads'] if s.id == candidate.squad_id):
                    raise PlanningConflict('The suggested member no longer fits skill, availability, squad or capacity requirements.')
                self._write_assignment(db, task, candidate.squad_id, candidate.member_id)
                projected = [EngineeringTask.model_validate({**item.model_dump(), 'assignee_id': candidate.member_id, 'squad_id': candidate.squad_id}) if item.id == task.id else item for item in projected]
        return self.snapshot(project_id)
