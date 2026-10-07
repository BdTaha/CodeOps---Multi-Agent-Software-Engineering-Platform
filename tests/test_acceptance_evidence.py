"""Real artifact provenance, conservative status resolution and durable audit gates."""
import json
import time
from uuid import uuid4
from pathlib import Path
import pytest
from sqlalchemy import select, update, insert, delete, inspect
from autonomous_engineering.domain.acceptance_evidence import CriterionSnapshot, EvidenceSource, EvidenceMapping, EvidenceContext
from autonomous_engineering.application.acceptance_mapper import artifact_sources, map_evidence
from autonomous_engineering.infrastructure.acceptance_tables import evidence_runs, run_criteria, evidence_items, acceptance_audits
from autonomous_engineering.infrastructure.acceptance_store import AcceptanceEvidenceStore
from autonomous_engineering.infrastructure.planning_store import criteria, PlanningStore
from autonomous_engineering.infrastructure.ollama_evidence import OllamaEvidenceProvider
from autonomous_engineering.workflows.state import WorkflowState
from test_task_execution_bridge import bridge, first, start, success, worker_for
from test_planner import ollama_server
from autonomous_engineering.core.config import Settings
from test_team_migration import legacy

def criterion(description='Expired tokens are rejected'):
    return CriterionSnapshot(id=uuid4(),description=description)

def source(kind='automated_test',executed=True,negative=False,explicit=()):
    return EvidenceSource(id='test:0:Fixture.test_expiry',evidence_type=kind,executed=executed,
        reference=dict(artifact='tests',test_identifier='Fixture.test_expiry',test_file='tests/test_reset.py',outcome='passed'),
        summary='Actual recorded artifact',negative=negative,explicit_criteria=explicit)

def test_verified_requires_explicit_recorded_execution_and_semantics_never_promote():
    c=criterion();s=source(explicit=(c.id,))
    assert map_evidence([c],[s])[0]['status']=='verified'
    for kind in ('code_change','reviewer'):
        assert map_evidence([c],[source(kind,False,explicit=(c.id,))])[0]['status']=='supported'
    proposal=EvidenceMapping(associations=[dict(criterion_id=c.id,source_id=s.id)])
    assert map_evidence([c],[source()],proposal)[0]['status']=='supported'
    assert map_evidence([c],[])[0]['status']=='unverified'

def test_negative_evidence_overrides_pass_and_unmapped_concerns_are_visible():
    c=criterion();passed=source(explicit=(c.id,));negative=source('reviewer',False,True).model_copy(update={'id':'review:0'})
    result=map_evidence([c],[passed,negative])[0]
    assert result['status']=='unverified' and result['conflict']
    assert result['sources'][1][1]=='unresolved_scope'

def test_semantic_negative_scope_cannot_hide_a_conflict_on_a_verified_requirement():
    a,b=criterion(),criterion('Another requirement')
    passed=source(explicit=(a.id,));negative=source('reviewer',False,True).model_copy(update={'id':'review:0'})
    proposal=EvidenceMapping(associations=[dict(criterion_id=b.id,source_id=negative.id)])
    results=map_evidence([a,b],[passed,negative],proposal)
    assert all(row['conflict'] and row['status']=='unverified' for row in results)

@pytest.mark.parametrize('reference',['invented_test','invented_file','invented_criterion','verification_override'])
def test_unknown_or_prose_model_references_are_rejected(reference):
    c=criterion();s=source()
    mapping=dict(associations=[dict(criterion_id=str(c.id),source_id=s.id)])
    if reference=='invented_criterion':mapping['associations'][0]['criterion_id']=str(uuid4())
    elif reference=='verification_override':mapping['associations'][0]['verification_status']='verified'
    else:mapping['associations'][0]['source_id']=reference
    with pytest.raises(ValueError):map_evidence([c],[s],mapping)

def replace_criterion(bridge,description):
    task=first(bridge)
    with bridge[2].engine.begin() as db:db.execute(update(criteria).where(criteria.c.task_id==str(task.id)).values(description=description))
    return first(bridge)

def current(bridge):return bridge[0].get(f'/engineering-tasks/{first(bridge).id}/execution').json()

def accept(bridge,evidence,ack=False):
    result=current(bridge)
    return bridge[0].post(f"/engineering-tasks/{result['task']['id']}/accept",json=dict(revision=result['task']['revision'],
        execution_task_id=result['execution']['id'],evidence_version=evidence.get('version'),unresolved_acknowledged=ack))

def test_real_passing_test_explicitly_maps_with_provenance_and_accepts_without_ack(bridge):
    task=replace_criterion(bridge,'The test_trim check passes')
    result,*_=success(bridge);evidence=result['acceptance_evidence']
    assert evidence['state']=='ready' and evidence['counts']==dict(verified=1,supported=0,unverified=0,conflict=0)
    row=evidence['criteria'][0];assert row['criterion_id']==str(task.acceptance_criteria[0].id)
    proof=row['evidence'][0];assert proof['executed'] and proof['mapping']=='deterministic'
    assert proof['reference']['test_file']=='tests/test_app.py' and proof['reference']['test_identifier']=='test_app.Greeting.test_trim'
    assert proof['reference']['outcome']=='passed'
    assert accept(bridge,evidence).status_code==200
    audit=current(bridge)['acceptance_evidence']['acceptance']
    assert not audit['unresolved_acknowledged'] and audit['action']=='local_human_acceptance'
    assert audit['evidence_digest'] and audit['evidence_version']==evidence['version']
    assert bridge[2].get(result['execution']['id'])['delivery']=={}

def test_unverified_requires_ack_and_evidence_is_not_recomputed_by_reads_or_restarts(bridge):
    result,*_=success(bridge);evidence=result['acceptance_evidence']
    assert evidence['criteria'][0]['verification_status']=='unverified'
    refused=accept(bridge,evidence);assert refused.status_code==409 and 'acknowledge' in refused.text
    assert current(bridge)['task']['status']=='review'
    assert accept(bridge,evidence,True).status_code==200
    assert current(bridge)['acceptance_evidence']['acceptance']['unresolved_acknowledged']
    before=AcceptanceEvidenceStore(bridge[7],bridge[2]).get(result['execution']['id'])
    PlanningStore(bridge[2].engine)
    assert AcceptanceEvidenceStore(bridge[7],bridge[2]).get(result['execution']['id'])==before
    assert bridge[0].get(f"/tasks/{result['execution']['id']}/acceptance-evidence").json()==before

def test_generation_failure_preserves_success_and_requires_ack(bridge,monkeypatch):
    import autonomous_engineering.infrastructure.acceptance_store as module
    def broken(*args):raise ValueError('Explicit fixture mapper failure')
    monkeypatch.setattr(module,'artifact_sources',broken)
    result,*_=success(bridge);job_id=result['execution']['id'];evidence=result['acceptance_evidence']
    assert evidence['state']=='unavailable' and not any(c['evidence'] for c in evidence['criteria'])
    assert bridge[2].get(job_id)['phase']=='succeeded' and result['task']['status']=='review'
    assert accept(bridge,evidence).status_code==409
    assert accept(bridge,evidence,True).status_code==200

def test_pending_evidence_has_no_false_ready_or_accidental_acceptance(bridge):
    response=start(bridge);job_id=response.json()['execution']['id'];worker,*_=worker_for(bridge)
    worker.run_once();job=bridge[2].get(job_id)
    bridge[0].post(f'/tasks/{job_id}/approve',json=dict(approval_id=job['approval'],run_tests=True,test_backend='local',framework='unittest',max_attempts=1))
    worker.run_once();result=current(bridge);evidence=result['acceptance_evidence']
    assert result['task']['status']=='review' and evidence['state']=='pending' and evidence['counts'] is None
    assert accept(bridge,evidence,True).status_code==409
    cap=bridge[0].get(f"/workspace/members/{bridge[5]['id']}/capacity").json()
    assert cap['active_execution_count']==0 and cap['assigned_queue_depth']==4
    assert worker.run_once() and current(bridge)['acceptance_evidence']['state']=='ready'

def test_request_changes_freezes_new_criteria_and_preserves_old_evidence(bridge):
    original,*_=success(bridge);task=original['task'];job=original['execution']
    old=AcceptanceEvidenceStore(bridge[7],bridge[2]).get(job['id'])
    response=bridge[0].post(f"/engineering-tasks/{task['id']}/request-changes",json=dict(revision=task['revision'],execution_task_id=job['id'],feedback='Keep greeting behavior and trim whitespace.'))
    assert response.status_code==202
    fresh=response.json();assert fresh['acceptance_evidence']['version']!=old['version']
    assert fresh['acceptance_evidence']['state']=='waiting' and fresh['execution']['id']!=job['id']
    assert fresh['acceptance_evidence']['criteria'][0]['criterion_id']==old['criteria'][0]['criterion_id']
    with bridge[2].engine.begin() as db:db.execute(update(criteria).where(criteria.c.task_id==task['id']).values(description='A future edited requirement'))
    assert current(bridge)['acceptance_evidence']['criteria'][0]['description']==old['criteria'][0]['description']
    assert AcceptanceEvidenceStore(bridge[7],bridge[2]).get(job['id'])==old

def test_specific_source_reference_checks_and_aggregate_pass_never_verify(bridge):
    replace_criterion(bridge,'The test_trim check passes')
    result,*_=success(bridge);state=WorkflowState.model_validate(result['execution']['snapshot'])
    frozen=[CriterionSnapshot(id=c['criterion_id'],description=c['description']) for c in result['acceptance_evidence']['criteria']]
    values=state.model_dump();values['tests']['executions'][0]['output_summary']='100 passed'
    sources=artifact_sources(WorkflowState.model_validate(values),bridge[7].workspace_root,frozen)
    assert not any(s.evidence_type=='automated_test' for s in sources)
    values['tests']['executions'][0]['output_summary']='test_invented (unknown.Fixture.test_invented) ... ok'
    assert not any(s.evidence_type=='automated_test' for s in artifact_sources(WorkflowState.model_validate(values),bridge[7].workspace_root,frozen))
    values=state.model_dump();values['changes'][0]['path']='invented.py';values['development']['changes']=values['changes']
    with pytest.raises(ValueError,match='file reference'):artifact_sources(WorkflowState.model_validate(values),bridge[7].workspace_root,frozen)

def test_old_successful_runs_are_not_backfilled_and_ack_is_audited(bridge):
    result,*_=success(bridge);execution_id=result['execution']['id']
    # Explicit pre-phase fixture: retained successful run without materialization.
    with bridge[2].engine.begin() as db:
        db.execute(delete(evidence_items).where(evidence_items.c.execution_task_id==execution_id))
        db.execute(delete(run_criteria).where(run_criteria.c.execution_task_id==execution_id))
        db.execute(delete(evidence_runs).where(evidence_runs.c.execution_task_id==execution_id))
    PlanningStore(bridge[2].engine)
    evidence=current(bridge)['acceptance_evidence'];assert evidence['state']=='not_generated'
    assert accept(bridge,evidence).status_code==409 and accept(bridge,evidence,True).status_code==200
    with bridge[2].engine.connect() as db:
        audit=db.execute(select(acceptance_audits).where(acceptance_audits.c.execution_task_id==execution_id)).mappings().one()
    assert audit['evidence_state']=='not_generated' and audit['unresolved_acknowledged'] and audit['evidence_version'] is None

def test_semantic_provider_uses_existing_transport_and_bounded_catalog(ollama_server):
    c=criterion();s=source();context=EvidenceContext(task=dict(repository_path='.',user_request='Fixture'),criteria=[c],sources=[s])
    response=json.dumps(dict(associations=[dict(criterion_id=str(c.id),source_id=s.id)]))
    url,behavior,captured=ollama_server
    behavior['body']={'done':True,'done_reason':'stop','message':{'content':response}}
    provider=OllamaEvidenceProvider(Settings(_env_file=None,ollama_model='explicit-fixture',ollama_base_url=url))
    mapping=provider.generate(context)
    assert map_evidence([c],[s],mapping)[0]['status']=='supported'
    schema=captured[0][1]['format']['$defs']['EvidenceAssociation']['properties']
    assert schema['source_id']['enum']==[s.id] and schema['criterion_id']['enum']==[str(c.id)]

def test_criterion_id_migration_preserves_old_text_positions_and_stable_identity(legacy):
    engine,identities=legacy
    # This fixture predates both evidence and workspace identity migrations.
    with engine.begin() as db:
        db.exec_driver_sql('DROP TABLE engineering_acceptance_criteria')
        db.exec_driver_sql('CREATE TABLE engineering_acceptance_criteria (task_id VARCHAR(36) NOT NULL REFERENCES engineering_tasks(id), position INTEGER NOT NULL, description TEXT NOT NULL, PRIMARY KEY (task_id,position))')
        for item in identities:
            db.execute(insert(criteria).values(task_id=item['task_id'],position=1,description='Second preserved requirement'))
            db.execute(insert(criteria).values(task_id=item['task_id'],position=0,description='First preserved requirement'))
    planning=PlanningStore(engine)
    before=[planning.task(item['task_id']).acceptance_criteria for item in identities]
    assert all([c.description for c in row]==['First preserved requirement','Second preserved requirement'] for row in before)
    assert len({c.id for row in before for c in row})==6
    PlanningStore(engine)
    assert [planning.task(item['task_id']).acceptance_criteria for item in identities]==before

def test_interrupted_mapper_is_unavailable_after_worker_restart(bridge):
    result,*_=success(bridge);execution_id=result['execution']['id']
    with bridge[2].engine.begin() as db:
        db.execute(update(evidence_runs).where(evidence_runs.c.execution_task_id==execution_id)
            .values(state='processing',owner='stopped-worker',lease=time.time()-1))
    restarted=AcceptanceEvidenceStore(bridge[7],bridge[2])
    assert not restarted.run_once('new-worker')
    evidence=current(bridge)['acceptance_evidence']
    assert evidence['state']=='unavailable' and 'INTERRUPTED' in evidence['error']
    assert bridge[2].get(execution_id)['phase']=='succeeded'

def test_real_review_conflict_requires_ack_and_keeps_passing_test_visible(bridge):
    from test_reviewer import FixtureReview
    replace_criterion(bridge,'The test_trim check passes')
    response=start(bridge);execution_id=response.json()['execution']['id'];worker,*_=worker_for(bridge)
    worker.review_provider=FixtureReview(dict(approved=True,summary='Fixture approved with a remaining medium concern.',findings=[dict(
        severity='medium',description='Fixture concern: strip removes all whitespace, inspect applicability to the requested behavior.',
        recommended_fix='Consider constraining whitespace policy after human review.',file='app.py',line=2,evidence="return 'Hello ' + name.strip()")]))
    worker.run_once();job=bridge[2].get(execution_id)
    bridge[0].post(f'/tasks/{execution_id}/approve',json=dict(approval_id=job['approval'],run_tests=True,test_backend='local',framework='unittest',max_attempts=1))
    worker.run_once();assert bridge[2].get(execution_id)['phase']=='succeeded'
    worker.run_once();evidence=current(bridge)['acceptance_evidence']
    assert evidence['state']=='ready' and evidence['counts']['conflict']==1 and evidence['counts']['verified']==0
    row=evidence['criteria'][0];assert row['conflict'] and row['verification_status']=='unverified'
    assert any(item['negative'] for item in row['evidence']) and any(item['executed'] for item in row['evidence'])
    assert accept(bridge,evidence).status_code==409
    assert accept(bridge,evidence,True).status_code==200

def test_nonexistent_reviewer_file_and_missing_mapper_version_fail_conservatively(bridge):
    result,*_=success(bridge);values=result['execution']['snapshot']
    values['review']['findings']=[dict(severity='medium',description='Fixture finding',recommended_fix='Fixture fix',file='invented.py')]
    frozen=[CriterionSnapshot(id=c['criterion_id'],description=c['description']) for c in result['acceptance_evidence']['criteria']]
    with pytest.raises(ValueError,match='Reviewer file reference'):
        artifact_sources(WorkflowState.model_validate(values),bridge[7].workspace_root,frozen)
    result=current(bridge);body=dict(revision=result['task']['revision'],execution_task_id=result['execution']['id'],unresolved_acknowledged=True)
    assert bridge[0].post(f"/engineering-tasks/{result['task']['id']}/accept",json=body).status_code==409

def test_exact_docstring_supports_recorded_test_without_fuzzy_matching(bridge):
    task=first(bridge);path=Path(bridge[4][0]['path'],'tests/test_app.py')
    text=path.read_text(encoding='utf-8').replace('def test_trim(self):','def test_trim(self):\n        """Leading and trailing whitespace is ignored"""')
    path.write_text(text,encoding='utf-8')
    result,*_=success(bridge)
    assert result['acceptance_evidence']['counts']['verified']==1

def test_semantic_reviewer_association_is_support_only(bridge):
    result,*_=success(bridge);execution_id=result['execution']['id']
    with bridge[2].engine.begin() as db:
        # Explicit fixture materialization requeue, only before human acceptance.
        db.execute(update(evidence_runs).where(evidence_runs.c.execution_task_id==execution_id).values(state='pending'))
    class ExplicitSemanticProvider:
        def generate(self,context):
            return EvidenceMapping(associations=[dict(criterion_id=context.criteria[0].id,source_id=next(s.id for s in context.sources if s.evidence_type=='code_change'))])
    mapper=AcceptanceEvidenceStore(bridge[7],bridge[2],ExplicitSemanticProvider())
    assert mapper.run_once('fixture-semantic')
    assert current(bridge)['acceptance_evidence']['counts']['supported']==1

def test_worker_uses_configured_ollama_mapper_public_interface(bridge,ollama_server):
    response=start(bridge);execution_id=response.json()['execution']['id'];worker,*_=worker_for(bridge)
    worker.run_once();job=bridge[2].get(execution_id)
    bridge[0].post(f'/tasks/{execution_id}/approve',json=dict(approval_id=job['approval'],run_tests=True,test_backend='local',framework='unittest',max_attempts=1))
    worker.run_once();assert current(bridge)['acceptance_evidence']['state']=='pending'
    url,behavior,captured=ollama_server
    cid=current(bridge)['acceptance_evidence']['criteria'][0]['criterion_id']
    behavior['body']={'done':True,'done_reason':'stop','message':{'content':json.dumps(dict(associations=[dict(criterion_id=cid,source_id='change:0')]))}}
    settings=Settings(_env_file=None,repository_root=bridge[7].repository_root,workspace_root=bridge[7].workspace_root,
        ollama_model='explicit-provider-fixture',ollama_base_url=url)
    assert AcceptanceEvidenceStore(settings,bridge[2]).run_once('fixture-configured-provider')
    assert current(bridge)['acceptance_evidence']['state']=='ready'
    assert current(bridge)['acceptance_evidence']['counts']['supported']==1
    assert len(captured)==1 and captured[0][1]['model']=='explicit-provider-fixture'
