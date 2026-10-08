"""Durable post-success evidence work, isolated from development outcome."""
import hashlib
import json
import logging
import time
from uuid import uuid4
from sqlalchemy import insert, select, update
from autonomous_engineering.domain.base import utc_now
from autonomous_engineering.domain.acceptance_evidence import CriterionSnapshot, EvidenceContext, MAPPER_VERSION
from autonomous_engineering.infrastructure.acceptance_tables import evidence_runs, run_criteria, evidence_items, acceptance_audits
from autonomous_engineering.infrastructure.task_store import tasks
from autonomous_engineering.infrastructure.task_execution_tables import execution_links, fence_execution
from autonomous_engineering.infrastructure.planning_store import PlanningConflict
from autonomous_engineering.workflows.state import WorkflowState
from autonomous_engineering.application.acceptance_mapper import artifact_sources, map_evidence

logger=logging.getLogger(__name__)

def freeze_requirements(db, execution_id, criteria):
    db.execute(insert(evidence_runs).values(execution_task_id=str(execution_id),version=str(uuid4()),
        mapper_version=MAPPER_VERSION,state='waiting',created_at=utc_now().isoformat()))
    for position,criterion in enumerate(criteria):
        db.execute(insert(run_criteria).values(execution_task_id=str(execution_id),criterion_id=str(criterion.id),
            position=position,description=criterion.description,verification_status='unverified',conflict=False))

def queue_evidence(db, execution_id):
    db.execute(update(evidence_runs).where(evidence_runs.c.execution_task_id==str(execution_id),evidence_runs.c.state=='waiting').values(state='pending'))

def evidence_snapshot(db, execution_id):
    row=db.execute(select(evidence_runs).where(evidence_runs.c.execution_task_id==str(execution_id))).mappings().first()
    if not row:
        return dict(state='not_generated',version=None,mapper_version=None,criteria=[],counts=None,error=None,acceptance=None)
    result=dict(row);result.pop('owner');result.pop('lease')
    items=[{**dict(item),'reference':json.loads(item['reference'])} for item in db.execute(select(evidence_items)
        .where(evidence_items.c.execution_task_id==str(execution_id)).order_by(evidence_items.c.created_at,evidence_items.c.id)).mappings()]
    result['criteria']=[{**dict(item),'evidence':[source for source in items if source['criterion_id']==item['criterion_id']]}
        for item in db.execute(select(run_criteria).where(run_criteria.c.execution_task_id==str(execution_id)).order_by(run_criteria.c.position)).mappings()]
    result['counts']= {status:sum(c['verification_status']==status and not c['conflict'] for c in result['criteria']) for status in ('verified','supported','unverified')}
    result['counts']['conflict']=sum(c['conflict'] for c in result['criteria'])
    if row['state']!='ready':result['counts']=None
    audit=db.execute(select(acceptance_audits).where(acceptance_audits.c.execution_task_id==str(execution_id))).mappings().first()
    result['acceptance']=dict(audit) if audit else None
    return result

def record_acceptance(db, execution_id, version, acknowledged, accepted_at):
    evidence=evidence_snapshot(db,execution_id)
    if evidence['version']!= (str(version) if version else None):
        raise PlanningConflict('Acceptance evidence changed. Refresh and review it before accepting.')
    unresolved=evidence['state']!='ready' or any(c['conflict'] or c['verification_status']=='unverified' for c in evidence['criteria'])
    # Pending work cannot silently complete after an acceptance audit was captured.
    if evidence['state'] in {'waiting','pending','processing'}:
        raise PlanningConflict('Acceptance evidence is still processing. Wait for it to finish before accepting.')
    if unresolved and not acknowledged:
        raise PlanningConflict('Explicitly acknowledge the unresolved criteria or unavailable evidence before accepting.')
    digest=hashlib.sha256(json.dumps(evidence,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    db.execute(insert(acceptance_audits).values(execution_task_id=str(execution_id),accepted_at=accepted_at,
        action='local_human_acceptance',evidence_version=evidence['version'],mapper_version=evidence['mapper_version'],
        evidence_state=evidence['state'],evidence_digest=digest,unresolved_acknowledged=acknowledged))

class AcceptanceEvidenceStore:
    def __init__(self, settings, store, provider=None):
        self.config,self.store,self.engine,self.provider=settings,store,store.engine,provider

    def get(self, execution_id):
        with self.engine.connect() as db:
            link=db.execute(select(execution_links).where(execution_links.c.execution_task_id==str(execution_id))).mappings().first()
            if not link: raise PlanningConflict('This execution has no originating EngineeringTask.')
            return {**evidence_snapshot(db,execution_id),'engineering_task_id':link['engineering_task_id'],'run_id':link['run_id']}

    def run_once(self, owner):
        now=time.time()
        with self.engine.begin() as db:
            # Interrupted mapping is visible and never automatically reinterpreted
            # under different artifacts or mapper versions after restart.
            db.execute(update(evidence_runs).where(evidence_runs.c.state=='processing',evidence_runs.c.lease<now)
                .values(state='unavailable',owner=None,lease=None,completed_at=utc_now().isoformat(),error='EVIDENCE_INTERRUPTED: Evidence processing stopped. Inspect retained artifacts manually.'))
            row=db.execute(select(evidence_runs).where(evidence_runs.c.state=='pending').order_by(evidence_runs.c.created_at).limit(1)).mappings().first()
            if not row:return False
            execution_id=row['execution_task_id']
            claimed=db.execute(update(evidence_runs).where(evidence_runs.c.execution_task_id==execution_id,evidence_runs.c.state=='pending')
                .values(state='processing',owner=owner,lease=now+self.config.planner_timeout_seconds+60))
            if claimed.rowcount!=1:return False
            job=db.execute(select(tasks).where(tasks.c.id==execution_id)).mappings().one()
            frozen=tuple(CriterionSnapshot(id=c['criterion_id'],description=c['description']) for c in db.execute(select(run_criteria)
                .where(run_criteria.c.execution_task_id==execution_id).order_by(run_criteria.c.position)).mappings())
        try:
            if row['mapper_version']!=MAPPER_VERSION:raise ValueError('This mapper version cannot process the queued evidence package.')
            if job['phase']!='succeeded':raise ValueError('Evidence requires final successful execution.')
            state=WorkflowState.model_validate_json(job['snapshot'])
            sources=artifact_sources(state,self.config.workspace_root,frozen)
            proposal=None
            deterministic=map_evidence(frozen,sources)
            # A configured model may add associations, never verification status.
            # No model is needed if there are no artifacts or all rows have strong
            # deterministic evidence (including visible negative findings).
            if sources and any(item['status']!='verified' and not item['conflict'] for item in deterministic):
                provider=self.provider
                from autonomous_engineering.infrastructure.model_gateway import model_configured
                if provider is None and model_configured(self.config):
                    from autonomous_engineering.infrastructure.model_evidence import GatewayEvidenceProvider
                    provider=GatewayEvidenceProvider(self.config)
                if provider:
                    if hasattr(provider, 'trace_observer'):
                        def observe(invocation):
                            with self.engine.begin() as db:
                                fence_execution(db, execution_id)
                                self.store.event(db, execution_id, 'model_invocation', 'acceptance_evidence', invocation.model_dump(mode='json'))
                        provider.trace_observer = observe
                    try:
                        proposal=provider.generate(EvidenceContext(task=state.task.request,criteria=frozen,sources=sources))
                    finally:
                        if hasattr(provider, 'trace_observer'): provider.trace_observer = None
            mapped=map_evidence(frozen,sources,proposal)
            with self.engine.begin() as db:
                fence_execution(db,execution_id)
                completed=db.execute(update(evidence_runs).where(evidence_runs.c.execution_task_id==execution_id,
                    evidence_runs.c.state=='processing',evidence_runs.c.owner==owner,evidence_runs.c.lease>time.time())
                    .values(state='ready',owner=None,lease=None,completed_at=utc_now().isoformat()))
                if completed.rowcount!=1:return True
                timestamp=utc_now().isoformat()
                for item in mapped:
                    cid=str(item['criterion'].id)
                    db.execute(update(run_criteria).where(run_criteria.c.execution_task_id==execution_id,run_criteria.c.criterion_id==cid)
                        .values(verification_status=item['status'],conflict=item['conflict']))
                    for source,mapping in item['sources']:
                        db.execute(insert(evidence_items).values(id=str(uuid4()),execution_task_id=execution_id,criterion_id=cid,
                            source_id=source.id,evidence_type=source.evidence_type,reference=json.dumps(source.reference),summary=source.summary,
                            negative=source.negative,executed=source.executed,mapping=mapping,created_at=timestamp))
                self.store.event(db,execution_id,'acceptance_evidence_ready',None,dict(mapper_version=MAPPER_VERSION,version=row['version']))
        except Exception:
            logger.exception('Acceptance evidence unavailable execution_task_id=%s',execution_id)
            with self.engine.begin() as db:
                failed=db.execute(update(evidence_runs).where(evidence_runs.c.execution_task_id==execution_id,evidence_runs.c.state=='processing',evidence_runs.c.owner==owner)
                    .values(state='unavailable',owner=None,lease=None,completed_at=utc_now().isoformat(),error='EVIDENCE_MAPPING_FAILED: Evidence could not be materialized. Inspect the raw artifacts manually.'))
                if failed.rowcount:self.store.event(db,execution_id,'acceptance_evidence_unavailable',None,dict(version=row['version']))
        return True
