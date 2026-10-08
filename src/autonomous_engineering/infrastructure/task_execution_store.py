"""Atomic bridge to existing execution jobs, with immutable run history."""
import json
from sqlalchemy import select, insert, update
from autonomous_engineering.domain.base import utc_now
from autonomous_engineering.domain.task_executions import ACTIVE_EXECUTION_PHASES
from autonomous_engineering.infrastructure.task_store import tasks, projects
from autonomous_engineering.infrastructure.planning_store import engineering_tasks, PlanningConflict
from autonomous_engineering.infrastructure.team_store import TeamNotFound
from autonomous_engineering.infrastructure.team_tables import lock_project
from autonomous_engineering.infrastructure.task_execution_tables import execution_links
from autonomous_engineering.application.execution_requests import execution_request
from autonomous_engineering.workflows.state import WorkflowState
from autonomous_engineering.infrastructure.delivery import receipt


class TaskExecutionStore:
    def __init__(self, config, store, teams):
        self.config, self.store, self.teams = config, store, teams
        self.engine = store.engine

    def _history(self, db, task_id):
        rows = db.execute(select(execution_links, tasks.c.phase, tasks.c.node).join(tasks,
            tasks.c.id == execution_links.c.execution_task_id).where(execution_links.c.engineering_task_id == str(task_id))
            .order_by(execution_links.c.created_at, execution_links.c.execution_task_id)).mappings()
        return [dict(row) for row in rows]

    def _context(self, db, task_id):
        row = db.execute(select(engineering_tasks).where(engineering_tasks.c.id == str(task_id))).mappings().first()
        if row is None:
            raise TeamNotFound('Engineering task not found.')
        snapshot = self.teams._snapshot(db, row['project_id'])
        task = next(item for item in snapshot['tasks'] if str(item.id) == str(task_id))
        owner = next((item for item in snapshot['workspace_members'] if item.id == task.assignee_id), None)
        history = self._history(db, task_id)
        latest = next((item for item in history if item['run_id'] == str(task.execution_run_id)), None)
        reasons = []
        if task.status == 'done': reasons.append('This task is Done.')
        if owner is None: reasons.append('Assign an AI developer to this task first.')
        elif owner.member_type != 'ai': reasons.append('Human-assigned tasks do not start AI execution.')
        else:
            if not owner.active: reasons.append('The workspace identity is inactive.')
            if owner.future_execution_role != 'developer': reasons.append('The AI identity must have the developer execution role.')
            if owner.availability == 'offline': reasons.append('The AI identity is offline.')
            joined = next((item for item in snapshot['memberships'] if item.member_id == owner.id), None)
            if joined is None or not joined.active: reasons.append('An active membership in this project is required.')
        indexed = {item.id:item for item in snapshot['workspace_tasks']}
        prerequisites = []
        for ref in task.dependencies:
            target = indexed.get(ref.task_id)
            prerequisites.append(dict(task_id=ref.task_id, key=target.key if target else 'Unknown prerequisite',
                title=target.title if target else '', status=target.status if target else 'missing'))
            if target is None or target.status != 'done': reasons.append(f'{target.key if target else ref.task_id} must be Done before running this task.')
        active = [item for item in history if item['phase'] in ACTIVE_EXECUTION_PHASES]
        if active: reasons.append('This task already has an active execution. Inspect or cancel it before retrying.')
        capacity = next((item for item in snapshot['capacities'] if item.member_id == task.assignee_id), None)
        count = capacity.active_execution_count if capacity else None
        if owner and owner.member_type == 'ai' and count >= owner.max_concurrent_executions:
            reasons.append(f'{owner.name} has reached execution capacity ({count} / {owner.max_concurrent_executions}). Assigned ownership remains queued.')
        if latest and latest['phase'] == 'succeeded':
            reasons.append('Review the successful result: accept it or request changes.')
        execution = self.store.unpack(db.execute(select(tasks).where(tasks.c.id == latest['execution_task_id'])).mappings().one()) if latest else None
        reviewable = bool(latest and latest['phase'] == 'succeeded' and latest['review_state'] == 'pending' and task.status == 'review')
        execution_owner = next((item for item in snapshot['workspace_members'] if latest and str(item.id)==latest['ai_member_id']),None)
        from autonomous_engineering.infrastructure.acceptance_store import evidence_snapshot
        return dict(task=task, owner=owner, execution_owner=execution_owner, current=latest, execution=execution, history=history,
            eligibility=dict(can_start=not reasons, reasons=reasons, dependencies=prerequisites,
                active_execution_count=count, max_concurrent_executions=owner.max_concurrent_executions if owner and owner.member_type=='ai' else None),
            can_accept=reviewable, can_request_changes=reviewable,
            acceptance_evidence=evidence_snapshot(db,latest['execution_task_id']) if latest else None)

    def snapshot(self, task_id):
        with self.teams._read() as db:
            return self._context(db, task_id)

    def _request(self, task, context, project, feedback=None):
        text = f'{task.key} — {task.title}\n\nDescription:\n{task.description}\n\nAcceptance criteria (requirements, not verified):\n'
        text += '\n'.join('- '+item.description for item in task.acceptance_criteria)
        text += f'\n\nTechnical area: {task.technical_area.value}\nProject repository: {project["path"]}\n'
        text += '\nCompleted prerequisites:\n' + '\n'.join(f'- {item["key"]}: {item["title"]} ({item["status"]})' for item in context['eligibility']['dependencies'])
        text += '\n\nThis task originated from the CodeOps engineering board. Inspect the repository to create a coding plan; human approval is required before code mutation.'
        if feedback:
            previous = context['execution']['snapshot'].get('development') or {}
            text += '\n\nHuman-requested changes:\n'+feedback
            text += '\n\nPrevious isolated result context (not applied to this fresh source snapshot):\n'+previous.get('explanation','')[:2000]
            text += '\nPrevious diff excerpt:\n'+previous.get('diff','')[:5000]
            text += '\nImplement the original requirements and feedback against the freshly inspected repository.'
        if len(text)>20000:
            raise ValueError('Task context exceeds the execution request limit. Shorten the task requirements before running.')
        return text

    def start(self, task_id, revision, feedback=None, previous_id=None):
        initial = self.teams.planning.task(task_id)
        if initial is None: raise TeamNotFound('Engineering task not found.')
        with self.engine.begin() as db:
            lock_project(db, initial.project_id)
            context = self._context(db, task_id)
            task = context['task']
            if task.revision != revision: raise PlanningConflict('Task changed. Refresh before starting execution.')
            if feedback:
                if not context['can_request_changes'] or context['current']['execution_task_id'] != str(previous_id):
                    raise PlanningConflict('Only the latest successful result awaiting human review can receive changes.')
                # Successful result is eligible for an explicit feedback run, but all
                # identity, dependency and concurrency restrictions still apply.
                context['eligibility']['reasons'] = [reason for reason in context['eligibility']['reasons'] if reason != 'Review the successful result: accept it or request changes.']
            if context['eligibility']['reasons']:
                raise PlanningConflict('Cannot start yet: '+' '.join(context['eligibility']['reasons']))
            project = json.loads(db.execute(select(projects.c.data).where(projects.c.id == str(task.project_id))).scalar_one())
            previous = context['current']
            effective_feedback = feedback or (previous.get('feedback') if previous and previous['phase'] in {'failed','cancelled'} else None)
            state, options = execution_request(self.config, project['path'], self._request(task, context, project, effective_feedback))
            self.store.create_in_transaction(db, state, options)
            from autonomous_engineering.infrastructure.acceptance_store import freeze_requirements
            freeze_requirements(db,state.task.task_id,task.acceptance_criteria)
            now = utc_now().isoformat()
            if feedback:
                from autonomous_engineering.infrastructure.preview_tables import stop_execution_previews
                stop_execution_previews(db,previous['execution_task_id'])
                db.execute(update(execution_links).where(execution_links.c.execution_task_id == previous['execution_task_id'])
                    .values(review_state='changes_requested', reviewed_at=now, feedback=feedback))
            db.execute(insert(execution_links).values(execution_task_id=str(state.task.task_id), run_id=str(state.run_id),
                engineering_task_id=str(task.id), ai_member_id=str(task.assignee_id),
                parent_execution_task_id=previous['execution_task_id'] if previous else None,
                created_at=now, review_state='pending', feedback=effective_feedback))
            db.execute(update(engineering_tasks).where(engineering_tasks.c.id == str(task.id), engineering_tasks.c.revision == revision)
                .values(execution_run_id=str(state.run_id), status='in_progress', revision=revision+1))
            self.store.event(db, str(state.task.task_id), 'engineering_task_linked', None,
                dict(engineering_task_id=str(task.id), key=task.key, ai_member_id=str(task.assignee_id)))
        return self.snapshot(task_id)

    def accept(self, task_id, revision, execution_id, evidence_version=None, unresolved_acknowledged=False):
        initial = self.teams.planning.task(task_id)
        if initial is None: raise TeamNotFound('Engineering task not found.')
        with self.engine.begin() as db:
            lock_project(db, initial.project_id)
            context = self._context(db, task_id)
            if context['task'].revision != revision: raise PlanningConflict('Task changed. Refresh before accepting.')
            if not context['can_accept'] or context['current']['execution_task_id'] != str(execution_id):
                raise PlanningConflict('Only the latest successful result in Review can be accepted.')
            # Reuse existing evidence/workspace validation; acceptance is not delivery.
            receipt(WorkflowState.model_validate(context['execution']['snapshot']), self.config.workspace_root)
            from autonomous_engineering.infrastructure.preview_tables import execution_previews
            from autonomous_engineering.domain.previews import ACTIVE_PREVIEWS
            if db.execute(select(execution_previews.c.id).where(execution_previews.c.execution_task_id==str(execution_id),
                    execution_previews.c.status.in_(ACTIVE_PREVIEWS))).first():
                raise PlanningConflict('Stop the active preview and wait for confirmed cleanup before accepting this result.')
            now = utc_now().isoformat()
            from autonomous_engineering.infrastructure.acceptance_store import record_acceptance
            record_acceptance(db,execution_id,evidence_version,unresolved_acknowledged,now)
            db.execute(update(execution_links).where(execution_links.c.execution_task_id == str(execution_id))
                .values(review_state='accepted', reviewed_at=now))
            db.execute(update(engineering_tasks).where(engineering_tasks.c.id == str(task_id))
                .values(status='done', revision=revision+1))
            self.store.event(db, str(execution_id), 'human_result_accepted', None, dict(engineering_task_id=str(task_id), accepted_at=now))
        return self.snapshot(task_id)
