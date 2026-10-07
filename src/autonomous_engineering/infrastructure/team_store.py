"""Workspace resources, project membership and globally fenced assignment writes."""
import json
from uuid import uuid4
from contextlib import contextmanager
from sqlalchemy import delete, insert, select, update
from autonomous_engineering.domain.base import utc_now
from autonomous_engineering.domain.teams import Squad, WorkspaceMember, ProjectMembership, MemberInput, MembershipInput
from autonomous_engineering.domain.product_planning import EngineeringTask
from autonomous_engineering.infrastructure.planning_store import PlanningConflict, engineering_tasks, goals
from autonomous_engineering.infrastructure.task_store import projects
from autonomous_engineering.infrastructure.team_tables import squads, members, skills, memberships, assignments, team_revisions, workspace_state, lock_project, lock_workspace
from autonomous_engineering.application.assignment_recommendations import capacities, recommend, assignment_warnings, dependency_warnings


class TeamNotFound(ValueError): pass


class AssignmentWarnings(ValueError):
    def __init__(self,warnings):
        self.warnings=warnings
        super().__init__('Review assignment warnings and explicitly allow them to continue.')


class TeamStore:
    def __init__(self,planning):
        self.planning=planning
        self.engine=planning.engine

    @contextmanager
    def _read(self):
        with self.engine.connect() as db:
            if db.dialect.name=='postgresql': db=db.execution_options(isolation_level='REPEATABLE READ')
            with db.begin():
                if db.dialect.name=='sqlite': db.exec_driver_sql('BEGIN')
                yield db

    def _squad(self,row):
        return Squad.model_validate({**dict(row),'technical_areas':json.loads(row['technical_areas'])})

    def _member(self,db,row):
        configured=[dict(item) for item in db.execute(select(skills.c.technical_area,skills.c.proficiency).where(skills.c.member_id==row['id']).order_by(skills.c.technical_area)).mappings()]
        return WorkspaceMember.model_validate({**dict(row),'skills':configured})

    def squad(self,identity):
        with self.engine.connect() as db:
            row=db.execute(select(squads).where(squads.c.id==str(identity))).mappings().first()
            return self._squad(row) if row else None

    def member(self,identity):
        with self.engine.connect() as db:
            row=db.execute(select(members).where(members.c.id==str(identity))).mappings().first()
            return self._member(db,row) if row else None

    def membership(self,identity):
        with self.engine.connect() as db:
            row=db.execute(select(memberships).where(memberships.c.id==str(identity))).mappings().first()
            return ProjectMembership.model_validate(row) if row else None

    def _workspace(self,db):
        roster=[self._member(db,row) for row in db.execute(select(members).order_by(members.c.created_at,members.c.id)).mappings()]
        joined=[ProjectMembership.model_validate(row) for row in db.execute(select(memberships).order_by(memberships.c.created_at,memberships.c.id)).mappings()]
        tasks=[self.planning._task(db,row) for row in db.execute(select(engineering_tasks).order_by(engineering_tasks.c.created_at,engineering_tasks.c.id)).mappings()]
        from autonomous_engineering.infrastructure.task_execution_tables import execution_links
        from autonomous_engineering.infrastructure.task_store import tasks as execution_jobs
        from autonomous_engineering.domain.task_executions import ACTIVE_EXECUTION_PHASES
        running = [dict(row) for row in db.execute(select(execution_links.c.ai_member_id,
            execution_links.c.engineering_task_id, execution_links.c.execution_task_id, execution_jobs.c.phase)
            .join(execution_jobs, execution_jobs.c.id==execution_links.c.execution_task_id)
            .where(execution_jobs.c.phase.in_(ACTIVE_EXECUTION_PHASES))).mappings()]
        names={row['id']:json.loads(row['data'])['name'] for row in db.execute(select(projects.c.id,projects.c.data)).mappings()}
        revision=db.execute(select(workspace_state.c.revision).where(workspace_state.c.id=='local')).scalar_one()
        loads = capacities(roster,tasks,names)
        for member in roster:
            if member.member_type=='ai':
                active = [item for item in running if item['ai_member_id']==str(member.id)]
                loads[member.id] = loads[member.id].model_copy(update={'active_execution_count':len(active), 'runtime_connected':True, 'active_executions':tuple(active)})
        return dict(members=roster,memberships=joined,tasks=tasks,capacities=list(loads.values()),
            projects=[dict(id=identity,name=name) for identity,name in names.items()],workspace_revision=revision)

    def workspace_snapshot(self):
        with self._read() as db: return self._workspace(db)

    def _snapshot(self,db,project_id):
        global_data=self._workspace(db)
        joined=[item for item in global_data['memberships'] if str(item.project_id)==str(project_id)]
        ids={item.member_id for item in joined}
        squad_list=[self._squad(row) for row in db.execute(select(squads).where(squads.c.project_id==str(project_id)).order_by(squads.c.created_at,squads.c.id)).mappings()]
        revision=db.execute(select(team_revisions.c.revision).where(team_revisions.c.project_id==str(project_id))).scalar_one_or_none() or 0
        latest=db.execute(select(goals.c.id,goals.c.status).where(goals.c.project_id==str(project_id)).order_by(goals.c.created_at.desc(),goals.c.id.desc()).limit(1)).mappings().first()
        return dict(squads=squad_list,members=[item for item in global_data['members'] if item.id in ids],memberships=joined,
            tasks=sorted((item for item in global_data['tasks'] if str(item.project_id)==str(project_id)),key=lambda item:int(item.key.split('-')[1])),
            capacities=global_data['capacities'],workspace_members=global_data['members'],workspace_memberships=global_data['memberships'],
            workspace_tasks=global_data['tasks'],projects=global_data['projects'],workspace_revision=global_data['workspace_revision'],
            project_revision=revision,current_plan_id=latest['id'] if latest and latest['status']=='ready' else None)

    def snapshot(self,project_id):
        with self._read() as db: return self._snapshot(db,project_id)

    def save_squad(self,project_id,body,squad_id=None):
        identity=str(squad_id or uuid4())
        with self.engine.begin() as db:
            lock_project(db,project_id)
            values=body.model_dump(mode='json',exclude={'revision'})
            values['technical_areas']=json.dumps(values['technical_areas'])
            if squad_id:
                changed=db.execute(update(squads).where(squads.c.id==identity,squads.c.project_id==str(project_id),squads.c.revision==body.revision).values(**values,revision=body.revision+1))
                if changed.rowcount!=1: raise PlanningConflict('Squad changed. Refresh and try again.')
            else: db.execute(insert(squads).values(**values,id=identity,project_id=str(project_id),revision=0,created_at=utc_now().isoformat()))
        return self.squad(identity)

    def _save_member(self,db,body,identity,existing=False):
        values=MemberInput.model_validate(body.model_dump(exclude={'revision','squad_id','membership_revision'})).model_dump(mode='json',exclude={'skills'})
        if existing:
            row=db.execute(select(members).where(members.c.id==identity)).mappings().first()
            if row is None: raise TeamNotFound('Workspace member not found.')
            if values['member_type']!=row['member_type']: raise ValueError('Member type cannot change. Create a separate identity.')
            if db.execute(update(members).where(members.c.id==identity,members.c.revision==body.revision).values(**values,revision=body.revision+1)).rowcount!=1:
                raise PlanningConflict('Workspace member changed. Refresh and try again.')
            db.execute(delete(skills).where(skills.c.member_id==identity))
        else: db.execute(insert(members).values(**values,id=identity,revision=0,created_at=utc_now().isoformat()))
        for skill in body.skills: db.execute(insert(skills).values(member_id=identity,technical_area=skill.technical_area.value,proficiency=skill.proficiency))

    def save_workspace_member(self,body,member_id=None):
        identity=str(member_id or uuid4())
        with self.engine.begin() as db:
            lock_workspace(db)
            self._save_member(db,body,identity,bool(member_id))
        return self.member(identity)

    def _save_membership(self,db,project_id,body,identity,existing=False):
        if not db.execute(select(squads.c.id).where(squads.c.id==str(body.squad_id),squads.c.project_id==str(project_id))).first():
            raise TeamNotFound('Squad does not belong to this project.')
        if existing:
            row=db.execute(select(memberships).where(memberships.c.id==identity)).mappings().first()
            if row is None: raise TeamNotFound('Project membership not found.')
            if db.execute(update(memberships).where(memberships.c.id==identity,memberships.c.revision==body.revision).values(squad_id=str(body.squad_id),active=body.active,revision=body.revision+1)).rowcount!=1:
                raise PlanningConflict('Project membership changed. Refresh and try again.')
            affected=select(assignments.c.task_id).join(engineering_tasks,assignments.c.task_id==engineering_tasks.c.id).where(assignments.c.assignee_id==row['member_id'],engineering_tasks.c.project_id==str(project_id))
            ids=list(db.execute(affected).scalars())
            if ids:
                from autonomous_engineering.infrastructure.task_execution_tables import active_for_task
                if any(active_for_task(db, task_id) for task_id in ids):
                    raise PlanningConflict('This membership owns an active execution. Cancel and wait before moving or deactivating it.')
                db.execute(update(engineering_tasks).where(engineering_tasks.c.id.in_(ids)).values(revision=engineering_tasks.c.revision+1))
                db.execute(update(assignments).where(assignments.c.task_id.in_(ids)).values(squad_id=str(body.squad_id)))
        else:
            if not db.execute(select(members.c.id).where(members.c.id==str(body.member_id))).first(): raise TeamNotFound('Workspace member not found.')
            if db.execute(select(memberships.c.id).where(memberships.c.project_id==str(project_id),memberships.c.member_id==str(body.member_id))).first():
                raise PlanningConflict('This member already has a project membership. Edit or reactivate it.')
            db.execute(insert(memberships).values(id=identity,project_id=str(project_id),member_id=str(body.member_id),squad_id=str(body.squad_id),active=body.active,created_at=utc_now().isoformat(),revision=0))

    def save_membership(self,project_id,body,membership_id=None):
        identity=str(membership_id or uuid4())
        with self.engine.begin() as db:
            lock_project(db,project_id)
            self._save_membership(db,project_id,body,identity,bool(membership_id))
        return self.membership(identity)

    def save_member(self,project_id,body,member_id=None):
        """Compatibility create-with-membership. Identity editing uses workspace API."""
        if member_id: raise ValueError('Edit workspace identity and project membership separately.')
        identity=str(uuid4())
        with self.engine.begin() as db:
            lock_project(db,project_id)
            self._save_member(db,body,identity)
            self._save_membership(db,project_id,MembershipInput(member_id=identity,squad_id=body.squad_id),str(uuid4()))
        result=self.member(identity).model_dump()
        result.update(project_id=project_id,squad_id=body.squad_id)
        return result

    def _write_assignment(self,db,task,squad_id,assignee_id):
        if db.execute(update(engineering_tasks).where(engineering_tasks.c.id==str(task.id),engineering_tasks.c.revision==task.revision).values(revision=task.revision+1)).rowcount!=1:
            raise PlanningConflict('Task changed. Refresh and try again.')
        db.execute(delete(assignments).where(assignments.c.task_id==str(task.id)))
        if squad_id is not None: db.execute(insert(assignments).values(task_id=str(task.id),squad_id=str(squad_id),assignee_id=str(assignee_id) if assignee_id else None,created_at=utc_now().isoformat()))

    def assign(self,task_id,body=None,revision=None):
        task=self.planning.task(task_id)
        if task is None: raise TeamNotFound('Engineering task not found.')
        with self.engine.begin() as db:
            lock_project(db,task.project_id)
            snapshot=self._snapshot(db,task.project_id)
            task=next(item for item in snapshot['tasks'] if item.id==task.id)
            if task.revision!=(body.revision if body else revision): raise PlanningConflict('Task changed. Refresh and try again.')
            from autonomous_engineering.infrastructure.task_execution_tables import active_for_task
            if active_for_task(db, task_id):
                raise PlanningConflict('This task has an active execution. Cancel it and wait for it to stop before changing ownership.')
            warnings=[]; squad_id=None; member_id=None
            if body:
                squad_id,member_id=body.squad_id,body.assignee_id
                if member_id:
                    joined=next((item for item in snapshot['memberships'] if item.member_id==member_id),None)
                    if joined is None: raise TeamNotFound('Member has no membership in this project.')
                    if not joined.active: raise PlanningConflict('Project membership is inactive. Reactivate it before assigning work.')
                    member=next(item for item in snapshot['members'] if item.id==member_id)
                    if squad_id and squad_id!=joined.squad_id: raise ValueError('Assignee must belong to the selected project squad.')
                    squad_id=joined.squad_id
                    squad=next(item for item in snapshot['squads'] if item.id==squad_id)
                    load=next(item for item in snapshot['capacities'] if item.member_id==member_id)
                    warnings=assignment_warnings(task,member,squad,load,snapshot['workspace_tasks'])
                elif not any(item.id==squad_id for item in snapshot['squads']): raise TeamNotFound('Squad does not belong to this project.')
                else: warnings=dependency_warnings(task,snapshot['workspace_tasks'])
                if warnings and not body.override_warnings: raise AssignmentWarnings(warnings)
            self._write_assignment(db,task,squad_id,member_id)
        return dict(task=self.planning.task(task_id),warnings=warnings)

    def recommendations(self,task_id):
        task=self.planning.task(task_id)
        if task is None: raise TeamNotFound('Engineering task not found.')
        snapshot=self.snapshot(task.project_id)
        task=next(item for item in snapshot['tasks'] if item.id==task.id)
        return dict(recommendations=recommend(task,snapshot['workspace_members'],snapshot['squads'],snapshot['workspace_tasks'],snapshot['memberships']),
            warnings=dependency_warnings(task,snapshot['workspace_tasks']),project_revision=snapshot['project_revision'],workspace_revision=snapshot['workspace_revision'])

    def suggested_plan(self,project_id):
        snapshot=self.snapshot(project_id)
        projected=list(snapshot['workspace_tasks']); suggestions=[]; unfilled=[]
        priorities={'urgent':0,'high':1,'medium':2,'low':3}
        eligible=sorted((task for task in snapshot['tasks'] if str(task.plan_id)==snapshot['current_plan_id'] and task.assignee_id is None and task.status!='done'),key=lambda task:(priorities[task.priority],int(task.key.split('-')[1])))
        for task in eligible:
            options=recommend(task,snapshot['workspace_members'],snapshot['squads'],projected,snapshot['memberships'])
            candidate=next((option for option in options if option.fits_capacity and task.technical_area in next(s.technical_areas for s in snapshot['squads'] if s.id==option.squad_id)),None)
            if candidate is None:
                unfilled.append(dict(task_id=task.id,key=task.key,reason='No eligible project member with matching skill, squad and global human capacity.'));continue
            suggestions.append(dict(task_id=task.id,key=task.key,title=task.title,revision=task.revision,assignee_id=candidate.member_id,squad_id=candidate.squad_id,reasons=candidate.reasons,warnings=candidate.warnings))
            projected=self._project(projected,task,candidate)
        return dict(project_revision=snapshot['project_revision'],workspace_revision=snapshot['workspace_revision'],suggestions=suggestions,unfilled=unfilled)

    def _project(self,tasks,task,candidate):
        return [EngineeringTask.model_validate({**item.model_dump(),'assignee_id':candidate.member_id,'squad_id':candidate.squad_id}) if item.id==task.id else item for item in tasks]

    def apply(self,project_id,body):
        with self.engine.begin() as db:
            lock_project(db,project_id,body.project_revision,body.workspace_revision)
            snapshot=self._snapshot(db,project_id)
            projected=list(snapshot['workspace_tasks'])
            for selection in body.assignments:
                task=next((task for task in projected if task.id==selection.task_id and str(task.project_id)==str(project_id) and str(task.plan_id)==snapshot['current_plan_id']),None)
                if task is None: raise TeamNotFound('Task is not in this project\'s current plan.')
                if task.revision!=selection.revision or task.assignee_id is not None: raise PlanningConflict('Assignment changed. Refresh recommendations.')
                candidate=next((item for item in recommend(task,snapshot['workspace_members'],snapshot['squads'],projected,snapshot['memberships']) if item.member_id==selection.assignee_id and item.fits_capacity),None)
                if candidate is None or task.technical_area not in next(s.technical_areas for s in snapshot['squads'] if s.id==candidate.squad_id):
                    raise PlanningConflict('Suggested member no longer fits membership, skill, availability, squad or global capacity requirements.')
                self._write_assignment(db,task,candidate.squad_id,candidate.member_id)
                projected=self._project(projected,task,candidate)
        return self.snapshot(project_id)
