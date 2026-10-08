"""Durable preview requests and independently reconciled lifecycle."""
import json
import time
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select, insert, update, func
from autonomous_engineering.domain.base import utc_now
from autonomous_engineering.domain.previews import PreviewProfileInput, ACTIVE_PREVIEWS
from autonomous_engineering.infrastructure.preview_tables import preview_profiles, execution_previews, lock_previews
from autonomous_engineering.infrastructure.task_store import projects
from autonomous_engineering.infrastructure.planning_store import PlanningConflict
from autonomous_engineering.infrastructure.team_store import TeamNotFound
from autonomous_engineering.infrastructure.delivery import receipt
from autonomous_engineering.infrastructure.docker_previews import DockerPreviewRuntime, PreviewRuntimeError
from autonomous_engineering.workflows.state import WorkflowState

class PreviewStore:
    def __init__(self, bridge, runtime=None):
        self.bridge=bridge;self.config=bridge.config;self.engine=bridge.engine
        self.runtime=runtime or DockerPreviewRuntime(self.config)

    def _profile(self,db,project_id):
        if not db.execute(select(projects.c.id).where(projects.c.id==str(project_id))).first(): raise TeamNotFound('Project not found.')
        row=db.execute(select(preview_profiles).where(preview_profiles.c.project_id==str(project_id))).mappings().first()
        return dict(json.loads(row['data']),id=row['id'],project_id=row['project_id'],revision=row['revision'],created_at=row['created_at']) if row else dict(PreviewProfileInput().model_dump(mode='json'),id=None,project_id=str(project_id),created_at=None)

    def profile(self,project_id):
        with self.engine.connect() as db: return self._profile(db,project_id)

    def save_profile(self,project_id,body):
        with self.engine.begin() as db:
            lock_previews(db);old=self._profile(db,project_id)
            if body.revision!=old['revision']: raise PlanningConflict('Preview profile changed. Refresh settings.')
            values=dict(data=body.model_dump_json(),revision=body.revision+1)
            if old['id']: db.execute(update(preview_profiles).where(preview_profiles.c.id==old['id']).values(**values))
            else: db.execute(insert(preview_profiles).values(id=str(uuid4()),project_id=str(project_id),created_at=utc_now().isoformat(),**values))
        return self.profile(project_id)

    def _eligible(self,context,profile):
        if not context['can_accept']: return 'Only the latest successful execution awaiting human review can start a preview.'
        if not profile.get('id') or not profile['enabled'] or profile['preview_type']=='none': return 'No interactive preview configured for this project. Use Acceptance, Diff, Tests and AI Review.'
        if profile['requires_external_services']: return 'Preview configuration requires unsupported external services. Use the verification package instead.'
        try: receipt(WorkflowState.model_validate(context['execution']['snapshot']),self.config.workspace_root)
        except ValueError as exc: return str(exc)
        return None

    def _serialize(self,row):
        result=dict(row);profile=json.loads(result.pop('profile_snapshot'));result.pop('owner');result.pop('lease');result.pop('active_execution_id')
        result['profile']=profile
        result['preview_url']=None;result['base_url']=None
        if result['status']=='ready' and result['host_port']:
            result['base_url']=f"http://127.0.0.1:{result['host_port']}"
            result['preview_url']=result['base_url']+profile['open_path']
        return result

    def get(self,preview_id):
        with self.engine.connect() as db:
            row=db.execute(select(execution_previews).where(execution_previews.c.id==str(preview_id))).mappings().first()
            if not row: raise TeamNotFound('Preview not found.')
            return self._serialize(row)

    def snapshot(self,task_id):
        with self.bridge.teams._read() as db:
            context=self.bridge._context(db,task_id);profile=self._profile(db,context['task'].project_id)
            rows=list(db.execute(select(execution_previews).where(execution_previews.c.engineering_task_id==str(task_id))
                .order_by(execution_previews.c.created_at,execution_previews.c.id)).mappings())
            reason=self._eligible(context,profile)
            current=next((r for r in reversed(rows) if context['current'] and r['execution_task_id']==context['current']['execution_task_id']),None)
            return dict(profile=profile,can_start=reason is None,reason=reason,current=self._serialize(current) if current else None,history=[self._serialize(row) for row in rows])

    def start(self,task_id,revision,execution_id):
        initial=self.bridge.teams.planning.task(task_id)
        if not initial: raise TeamNotFound('Engineering task not found.')
        with self.engine.begin() as db:
            lock_previews(db)
            context=self.bridge._context(db,task_id);profile=self._profile(db,initial.project_id)
            if context['task'].revision!=revision or not context['current'] or context['current']['execution_task_id']!=str(execution_id):
                raise PlanningConflict('Task/run changed. Refresh before previewing.')
            reason=self._eligible(context,profile)
            if reason: raise PlanningConflict(reason)
            active=db.execute(select(execution_previews.c.id).where(execution_previews.c.active_execution_id==str(execution_id))).scalar()
            if active: return self._serialize(db.execute(select(execution_previews).where(execution_previews.c.id==active)).mappings().one())
            count=db.execute(select(func.count()).select_from(execution_previews).where(execution_previews.c.status.in_(ACTIVE_PREVIEWS))).scalar_one()
            if count>=self.config.max_active_previews: raise PlanningConflict('Workspace preview limit reached. Stop a preview before starting another.')
            preview_id=str(uuid4());now=utc_now()
            data={key:profile[key] for key in PreviewProfileInput.model_fields};data['revision']=profile['revision']
            db.execute(insert(execution_previews).values(id=preview_id,engineering_task_id=str(task_id),execution_task_id=str(execution_id),
                run_id=context['current']['run_id'],profile_id=profile['id'],profile_snapshot=json.dumps(data),status='queued',
                active_execution_id=str(execution_id),created_at=now.isoformat(),expires_at=(now+timedelta(minutes=profile['ttl_minutes'])).isoformat(),logs=''))
        return self.get(preview_id)

    def stop(self,preview_id):
        with self.engine.begin() as db:
            lock_previews(db)
            row=db.execute(select(execution_previews).where(execution_previews.c.id==str(preview_id))).mappings().first()
            if not row: raise TeamNotFound('Preview not found.')
            if row['status'] in ACTIVE_PREVIEWS:
                db.execute(update(execution_previews).where(execution_previews.c.id==str(preview_id)).values(status='stopping',stop_reason='stopped'))
        return self.get(preview_id)

    def restart(self,preview_id,revision,execution_id):
        old=self.get(preview_id)
        if old['execution_task_id']!=str(execution_id): raise PlanningConflict('Restart must reference the same current execution.')
        if old['status'] in ACTIVE_PREVIEWS: raise PlanningConflict('Stop this preview and wait for cleanup before restarting.')
        return self.start(old['engineering_task_id'],revision,execution_id)

    def _update(self,row,owner,**values):
        with self.engine.begin() as db:
            lock_previews(db)
            changed=db.execute(update(execution_previews).where(execution_previews.c.id==row['id'],
                execution_previews.c.owner==owner,execution_previews.c.status.in_(('building','starting')),
                execution_previews.c.lease>time.time()).values(**values))
            if changed.rowcount!=1: raise PreviewRuntimeError('Preview was stopped, expired or its startup lease was lost.')

    def _guard(self,row,owner):
        with self.engine.begin() as db:
            lock_previews(db)
            current=db.execute(select(execution_previews).where(execution_previews.c.id==row['id'])).mappings().one()
            if current['owner']!=owner or current['status'] not in {'building','starting'} or current['lease']<=time.time() or current['expires_at']<=utc_now().isoformat():
                raise PreviewRuntimeError('Preview startup stopped or expired.')
            context=self.bridge._context(db,row['engineering_task_id'])
            if not context['can_accept'] or context['current']['execution_task_id']!=row['execution_task_id']:
                raise PreviewRuntimeError('Execution is no longer eligible for preview.')
            return context['execution']['snapshot']

    def _finish_cleanup(self,row):
        # Startup can still be in a Docker call. Wait for its bounded lease so cleanup
        # cannot race a late create/start and accidentally leave an orphan running.
        if row['owner'] and row['lease'] and row['lease']>time.time(): return False
        try:
            logs=self.runtime.logs(row) or row['logs'];self.runtime.cleanup(row)
        except PreviewRuntimeError as exc:
            with self.engine.begin() as db:
                db.execute(update(execution_previews).where(execution_previews.c.id==row['id'],execution_previews.c.status=='stopping')
                    .values(failure_reason=('Cleanup pending: '+str(exc))[:4000]))
            return False
        with self.engine.begin() as db:
            lock_previews(db)
            db.execute(update(execution_previews).where(execution_previews.c.id==row['id'],execution_previews.c.status=='stopping')
                .values(status=row['stop_reason'] or 'stopped',stopped_at=utc_now().isoformat(),active_execution_id=None,owner=None,lease=None,logs=logs[-16384:]))
        return True

    def reconcile(self):
        now=utc_now().isoformat()
        with self.engine.begin() as db:
            lock_previews(db)
            rows=list(db.execute(select(execution_previews).where(execution_previews.c.status.in_(ACTIVE_PREVIEWS))).mappings())
            for row in rows:
                reason=None
                if row['expires_at']<=now: reason='expired'
                elif row['status'] in {'building','starting'} and (not row['lease'] or row['lease']<=time.time()): reason='failed'
                elif row['status'] not in {'stopping'}:
                    context=self.bridge._context(db,row['engineering_task_id'])
                    if not context['can_accept'] or context['current']['execution_task_id']!=row['execution_task_id']: reason='stopped'
                if reason: db.execute(update(execution_previews).where(execution_previews.c.id==row['id'])
                    .values(status='stopping',stop_reason=reason,failure_reason='Preview startup interrupted.' if reason=='failed' else row['failure_reason']))
        with self.engine.connect() as db:
            rows=list(db.execute(select(execution_previews)).mappings())
        indexed={r['id']:r for r in rows}
        # Orphan names alone are insufficient: inspect and validate the full ownership labels.
        for name in self.runtime.owned_containers():
            info=self.runtime.inspect(name)
            if info is None: continue
            labels=info['Config'].get('Labels') or {};preview_id=labels.get('codeops.preview_id')
            row=indexed.get(preview_id)
            if row is None:
                from uuid import UUID
                try: UUID(preview_id);UUID(labels.get('codeops.execution_id'));UUID(labels.get('codeops.run_id'))
                except (ValueError,TypeError,AttributeError): continue
                orphan=dict(id=preview_id,execution_task_id=labels['codeops.execution_id'],run_id=labels['codeops.run_id'])
                if name in self.runtime.names(orphan)[:2] and self.runtime.owned(info,orphan): self.runtime.cleanup(orphan)
            elif row['status'] not in ACTIVE_PREVIEWS:
                self.runtime.cleanup(row)
        for kind in ('volume','network'):
            for name in self.runtime.owned_resources(kind):
                info=self.runtime.inspect(name,kind)
                if info is None: continue
                labels=info.get('Labels') or {}
                preview_id=labels.get('codeops.preview_id');row=indexed.get(preview_id)
                if row is not None and row['status'] not in ACTIVE_PREVIEWS:
                    self.runtime.cleanup(row)
                if row is None:
                    from uuid import UUID
                    try: UUID(preview_id);UUID(labels.get('codeops.execution_id'));UUID(labels.get('codeops.run_id'))
                    except (ValueError,TypeError,AttributeError): continue
                    orphan=dict(id=preview_id,execution_task_id=labels['codeops.execution_id'],run_id=labels['codeops.run_id'])
                    if name in self.runtime.names(orphan)[2:] and self.runtime.owned(info,orphan,kind): self.runtime.cleanup(orphan)
        for row in rows:
            if row['status']=='stopping': self._finish_cleanup(row)
            elif row['status']=='ready':
                info=self.runtime.resource(row,'container',self.runtime.names(row)[1])
                profile=json.loads(row['profile_snapshot'])
                if not info or not info['State']['Running'] or not self.runtime.healthy(row['host_port'],profile['health_path']):
                    with self.engine.begin() as db:
                        lock_previews(db)
                        db.execute(update(execution_previews).where(execution_previews.c.id==row['id'],execution_previews.c.status=='ready')
                            .values(status='stopping',stop_reason='failed',failure_reason='Preview container is missing, exited or unhealthy.'))
                else:
                    logs=self.runtime.logs(row)
                    with self.engine.begin() as db:
                        db.execute(update(execution_previews).where(execution_previews.c.id==row['id'],execution_previews.c.status=='ready').values(logs=logs[-16384:]))

    def run_once(self,owner):
        self.reconcile()
        with self.engine.begin() as db:
            lock_previews(db)
            row=db.execute(select(execution_previews).where(execution_previews.c.status=='queued')
                .order_by(execution_previews.c.created_at,execution_previews.c.id).limit(1)).mappings().first()
            if not row: return False
            row=dict(row);profile=json.loads(row['profile_snapshot'])
            lease=time.time()+profile['timeout_seconds']*2+90
            db.execute(update(execution_previews).where(execution_previews.c.id==row['id']).values(status='building',owner=owner,lease=lease))
        try:
            snapshot=self._guard(row,owner)
            values=self.runtime.launch(row,snapshot,lambda:self._guard(row,owner),lambda **values:self._update(row,owner,**values))
            with self.engine.begin() as db:
                lock_previews(db)
                context=self.bridge._context(db,row['engineering_task_id'])
                current=db.execute(select(execution_previews).where(execution_previews.c.id==row['id'])).mappings().one()
                if not context['can_accept'] or context['current']['execution_task_id']!=row['execution_task_id'] or current['status'] not in {'building','starting'} or current['owner']!=owner or current['lease']<=time.time() or current['expires_at']<=utc_now().isoformat():
                    raise PreviewRuntimeError('Preview no longer eligible after startup.')
                db.execute(update(execution_previews).where(execution_previews.c.id==row['id']).values(**values,status='ready',ready_at=utc_now().isoformat(),owner=None,lease=None))
        except Exception as exc:
            with self.engine.begin() as db:
                lock_previews(db)
                current=db.execute(select(execution_previews).where(execution_previews.c.id==row['id'])).mappings().one()
                db.execute(update(execution_previews).where(execution_previews.c.id==row['id'],execution_previews.c.owner==owner)
                    .values(status='stopping',stop_reason=current['stop_reason'] or ('expired' if current['expires_at']<=utc_now().isoformat() else 'failed'),failure_reason=str(exc)[:4000],owner=None,lease=None))
        finally:
            with self.engine.begin() as db:
                lock_previews(db)
                db.execute(update(execution_previews).where(execution_previews.c.id==row['id'],execution_previews.c.owner==owner).values(owner=None,lease=None))
            self.reconcile()
        return True
