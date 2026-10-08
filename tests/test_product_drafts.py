"""Planning trust boundary: real persistence, revisions and materialization."""
import copy
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, event, update

from autonomous_engineering.application.worker import Worker
from autonomous_engineering.domain.product_planning import ProductPlanDraft, PlanningBasis
from autonomous_engineering.infrastructure.planning_store import PlanningStore, PlanningConflict, goals, engineering_tasks, epics
from autonomous_engineering.infrastructure.planning_drafts import drafts, versions
from autonomous_engineering.infrastructure.team_store import TeamStore
from autonomous_engineering.infrastructure.task_store import TaskStore
from autonomous_engineering.platform import create_platform_app
from autonomous_engineering.tools.product_context import planning_context, MAX_FILES, MAX_TOTAL_BYTES
from autonomous_engineering.tools.repository import RepositoryError
from test_product_planning import product, Provider, draft_data


def generate(product):
    config,store,planning,project=product
    record=planning.enqueue(project['id'],'Add registration with validation and storage')
    provider=Provider()
    assert Worker(config,store,product_plan_provider=provider).run_once()
    saved=planning.get(record.goal.id)
    assert saved.status=='draft',saved.error
    return saved,provider


def test_grounding_reaches_provider_and_draft_is_durable_but_not_actionable(product):
    record,provider=generate(product)
    config,store,planning,project=product
    assert provider.contexts[0].repository.mode=='repository_grounded'
    assert 'app.py' in provider.contexts[0].repository.inspected_files
    assert record.plan is None and record.draft.tasks[0].ref=='T1'
    assert planning.tasks(project['id'])==()
    assert TeamStore(planning).snapshot(project['id'])['tasks']==[]
    assert TeamStore(planning).workspace_snapshot()['tasks']==[]
    reopened=TaskStore(store.engine.url.render_as_string(hide_password=False))
    try: assert PlanningStore(reopened.engine).get(record.goal.id).draft==record.draft
    finally: reopened.close()
    with TestClient(create_platform_app(config,store)) as client:
        assert client.get(f"/projects/{project['id']}/engineering-tasks").json()['tasks']==[]


def test_repository_context_excludes_secrets_binaries_links_and_raw_values(tmp_path):
    (tmp_path/'package.json').write_text(json.dumps({'dependencies':{'react':'https://user:secret-password@example.test/pkg'}}))
    (tmp_path/'.env').write_text('API_KEY=secret-password')
    (tmp_path/'.env.example').write_text('API_KEY=secret-password')
    (tmp_path/'credentials.json').write_text('{"key":"secret-password"}')
    (tmp_path/'binary.png').write_bytes(b'\x00secret-password')
    (tmp_path/'app.py').write_text('API_KEY="secret-password"')
    (tmp_path/'.git').mkdir();(tmp_path/'.git'/'config').write_text('secret-password')
    basis=planning_context({'path':str(tmp_path)},'Add authentication')
    text=basis.model_dump_json()
    assert 'secret-password' not in text and '.env' not in text and 'credentials.json' not in text and 'binary.png' not in text and '.git/config' not in text
    assert basis.analysis.frameworks==('React',)


def test_context_is_bounded_and_missing_repository_is_marked(tmp_path):
    for index in range(60): (tmp_path/f'file{index}.py').write_text('x=1\n'*10000)
    basis=planning_context({'path':str(tmp_path)},'Analyze')
    assert len(basis.inspected_files)<=MAX_FILES
    assert sum((tmp_path/path).stat().st_size for path in basis.inspected_files)<=MAX_TOTAL_BYTES
    assert len(basis.model_dump_json())<25000
    missing=planning_context({'path':str(tmp_path/'missing')},'Goal')
    assert missing.mode=='goal_only' and missing.reason and missing.analysis is None
    assert planning_context({},'Goal').mode=='goal_only'


def test_unexpected_context_failure_is_not_silently_goal_only(product,monkeypatch):
    def broken(*args): raise RuntimeError('Unexpected context bug')
    monkeypatch.setattr('autonomous_engineering.tools.product_context.planning_context',broken)
    config,store,planning,project=product
    record=planning.enqueue(project['id'],'Goal')
    provider=Provider();assert Worker(config,store,product_plan_provider=provider).run_once()
    failed=planning.get(record.goal.id)
    assert failed.status=='failed' and 'PLANNING_FAILED' in failed.error and not provider.contexts


def test_inventory_limit_remains_visible_instead_of_fallback(tmp_path):
    for index in range(2001): (tmp_path/f'{index}.py').touch()
    with pytest.raises(RepositoryError,match='file count'): planning_context({'path':str(tmp_path)},'Goal')


def test_goal_only_provenance_persists_and_reaches_provider(product):
    config,store,planning,project=product
    Path(project['path'],'app.py').unlink();Path(project['path']).rmdir()
    record,provider=generate(product)
    assert record.planning_basis.mode=='goal_only' and provider.contexts[0].repository.mode=='goal_only'


@pytest.mark.parametrize('change',['title','summary','assumptions','estimate','criteria','dependencies','add_task','remove_task','add_epic','remove_epic','move_task','priority','area'])
def test_valid_edits_persist_without_materializing(product,change):
    record,_=generate(product);planning=product[2];data=record.draft.model_dump(mode='json')
    if change in {'title','summary'}: data[change]='Human edited '+change
    elif change=='assumptions': data['assumptions']=['Human-reviewed assumption']
    elif change=='estimate': data['tasks'][0]['estimated_hours']=5
    elif change=='criteria': data['tasks'][0]['acceptance_criteria'].append({'description':'Passwords are hashed'})
    elif change=='dependencies': data['tasks'][1]['dependencies']=[]
    elif change=='priority': data['tasks'][0]['priority']='urgent'
    elif change=='area': data['tasks'][0]['technical_area']='Backend'
    elif change=='add_task': data['tasks'].append({**copy.deepcopy(data['tasks'][1]),'ref':'T3'})
    elif change=='remove_task': data['tasks']=data['tasks'][:1]
    else:
        data['epics'].append({'ref':'E2','title':'Second epic','description':'Human group'})
        data['tasks'][1]['epic_ref']='E2'
        if change=='remove_epic': data['epics']=data['epics'][1:];data['tasks']=data['tasks'][1:];data['tasks'][0]['dependencies']=[]
        if change=='move_task': data['tasks'][0]['epic_ref']='E2';data['epics']=data['epics'][1:]
    saved=planning.edit(record.goal.id,ProductPlanDraft.model_validate(data),0)
    assert saved.draft_revision==1 and saved.draft.model_dump(mode='json')==data
    assert planning.tasks(product[3]['id'])==()
    with planning.engine.connect() as db: assert len(list(db.execute(select(versions).where(versions.c.plan_id==str(record.goal.id)))))==2


@pytest.mark.parametrize('kind',['unknown','self','cycle','empty_criteria','empty_epic','estimate','priority','area','duplicate'])
def test_backend_rejects_invalid_draft_edits(product,kind):
    record,_=generate(product);data=draft_data()
    if kind=='unknown':data['tasks'][0]['dependencies']=['T99']
    elif kind=='self':data['tasks'][0]['dependencies']=['T1']
    elif kind=='cycle':data['tasks'][0]['dependencies']=['T2']
    elif kind=='empty_criteria':data['tasks'][0]['acceptance_criteria']=[]
    elif kind=='empty_epic':data['epics'].append({'ref':'E2','title':'Empty','description':'Empty'})
    elif kind=='estimate':data['tasks'][0]['estimated_hours']=25
    elif kind=='priority':data['tasks'][0]['priority']='invented'
    elif kind=='area':data['tasks'][0]['technical_area']='invented'
    elif kind=='duplicate':data['tasks'][1]['ref']='T1'
    with TestClient(create_platform_app(product[0],product[1])) as client:
        assert client.put(f'/product-plans/{record.goal.id}/draft',json={'revision':0,'draft':data}).status_code==422
    assert product[2].get(record.goal.id).draft_revision==0


def test_stale_edit_approval_immutability_numbering_and_previous_work(product):
    record,_=generate(product);planning=product[2]
    edited=planning.edit(record.goal.id,record.draft,0)
    with pytest.raises(PlanningConflict):planning.edit(record.goal.id,record.draft,0)
    with pytest.raises(PlanningConflict):planning.approve(record.goal.id,0)
    approved=planning.approve(record.goal.id,edited.draft_revision)
    assert [task.key for task in approved.plan.tasks]==['CO-1','CO-2']
    assert approved.materialization=={'T1':'CO-1','T2':'CO-2'} and approved.approved_at
    assert len(TeamStore(planning).snapshot(product[3]['id'])['tasks'])==2
    with pytest.raises(PlanningConflict):planning.edit(record.goal.id,record.draft,edited.draft_revision)
    with pytest.raises(PlanningConflict):planning.approve(record.goal.id,edited.draft_revision)
    next_record,_=generate(product)
    assert planning.get(record.goal.id).draft==edited.draft
    assert len(planning.tasks(product[3]['id']))==2  # Board does not lose approved work while a draft exists.
    new=planning.approve(next_record.goal.id,0)
    assert [task.key for task in new.plan.tasks]==['CO-3','CO-4']


def test_materialization_failure_rolls_back_every_table_and_key_allocation(product):
    record,_=generate(product);planning=product[2]
    def fail_insert(conn,clause,*args):
        if getattr(clause,'table',None) is engineering_tasks: raise RuntimeError('Injected materialization failure')
    event.listen(planning.engine,'before_execute',fail_insert)
    try:
        with pytest.raises(RuntimeError):planning.approve(record.goal.id,0)
    finally:event.remove(planning.engine,'before_execute',fail_insert)
    assert planning.get(record.goal.id).status=='draft'
    with planning.engine.connect() as db:
        assert not db.execute(select(epics)).first() and not db.execute(select(engineering_tasks)).first()
    assert planning.approve(record.goal.id,0).plan.tasks[0].key=='CO-1'


def test_concurrent_approval_has_one_winner(product):
    record,_=generate(product);planning=product[2];barrier=Barrier(2)
    def approve():
        barrier.wait()
        try:planning.approve(record.goal.id,0);return 'approved'
        except PlanningConflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(lambda _:approve(),range(2)))==['approved','conflict']
    assert len(planning.tasks(product[3]['id']))==2


def test_legacy_ready_compatibility_is_additive_and_preserves_work(product):
    record,_=generate(product);planning=product[2];approved=planning.approve(record.goal.id,0)
    with planning.engine.begin() as db:
        # Simulate an old ready plan: no draft/provenance record existed in that schema.
        from autonomous_engineering.infrastructure.planning_drafts import DRAFT_TABLES
        for table in reversed(DRAFT_TABLES):db.execute(table.delete().where(table.c.plan_id==str(record.goal.id)))
        db.execute(update(goals).where(goals.c.id==str(record.goal.id)).values(status='ready'))
    migrated=PlanningStore(planning.engine).get(record.goal.id)
    assert migrated.status=='approved' and migrated.legacy_approved and migrated.planning_basis.mode=='goal_only'
    assert [task.id for task in migrated.plan.tasks]==[task.id for task in approved.plan.tasks]
    assert len(TeamStore(planning).snapshot(product[3]['id'])['tasks'])==2
