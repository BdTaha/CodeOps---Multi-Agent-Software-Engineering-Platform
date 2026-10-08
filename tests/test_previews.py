"""Relational lifecycle tests with explicit fake transport; real Docker is opt-in."""
import io
import json
import os
import tarfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path
from uuid import uuid4
import pytest
from pydantic import ValidationError
from sqlalchemy import select, update
from fastapi.testclient import TestClient
from autonomous_engineering.domain.previews import PreviewProfileInput
from autonomous_engineering.infrastructure.preview_tables import execution_previews
from autonomous_engineering.infrastructure.preview_store import PreviewStore
from autonomous_engineering.infrastructure.docker_previews import DockerPreviewRuntime, PreviewRuntimeError
from autonomous_engineering.infrastructure.task_store import TaskStore, tasks
from autonomous_engineering.infrastructure.task_execution_tables import execution_links
from autonomous_engineering.infrastructure.delivery import receipt
from autonomous_engineering.workflows.state import WorkflowState
from autonomous_engineering.platform import create_platform_app
from test_task_execution_bridge import bridge, success, first, start, worker_for

class FakeRuntime:
    """Explicit lifecycle transport only; these assertions do not test Docker."""
    def __init__(self): self.running={};self.cleaned=[];self.fail=False;self.health=True;self.hook=None
    def launch(self,row,snapshot,guard,update):
        guard();update(status='starting',container_id='fake-'+row['id'],host_port=49000)
        self.running[row['id']]=True
        if self.hook:self.hook()
        guard()
        if self.fail or not self.health: raise PreviewRuntimeError('Explicit fixture startup/health failure')
        return dict(container_id='fake-'+row['id'],host_port=49000,source_digest='f'*64,logs='explicit fixture ready')
    def owned_containers(self): return []
    def owned_resources(self,kind): return []
    def names(self,row): return ('build','run','volume','network')
    def resource(self,row,kind,name): return {'State':{'Running':True}} if self.running.get(row['id']) else None
    def healthy(self,port,path): return self.health
    def logs(self,row): return 'explicit fixture logs'
    def cleanup(self,row): self.cleaned.append(row['id']);self.running.pop(row['id'],None)

def configured(bridge,**values):
    store=bridge[1].state.preview_store;fake=FakeRuntime();store.runtime=fake
    profile=dict(name='Fixture preview',preview_type='static',runtime='python',enabled=True,
        start_command=['python','-m','http.server','8000','--bind','0.0.0.0'],**values)
    response=bridge[0].put(f"/projects/{bridge[4][0]['id']}/preview-profile",json=profile)
    assert response.status_code==200,response.text
    return store,fake,response.json()

def request_preview(bridge,result):
    return bridge[0].post(f"/engineering-tasks/{result['task']['id']}/preview",
        json=dict(revision=result['task']['revision'],execution_task_id=result['execution']['id']))

@pytest.mark.parametrize('change',[
    {'container_port':0},{'container_port':65536},{'health_path':'//evil.test'},
    {'health_path':'/x\r\nHost:evil'},{'open_path':'http://evil.test'}, {'ttl_minutes':0},
    {'ttl_minutes':121},{'timeout_seconds':301},{'preview_type':'compose'}, {'runtime':'docker'},
    {'start_command':'npm run dev'}, {'start_command':['sh','-c','echo hello']},
    {'start_command':['/bin/sh','-c','echo hello']},{'build_commands':[[]]},
    {'environment':{'GITHUB_TOKEN':'secret'}},{'environment':{'PATH':'bad'}},
    {'environment':{'NODE_OPTIONS':'--require=x'}},{'environment':{'bad-key':'value'}},
    {'host_mounts':['/']},{'image':'untrusted:latest'}, {'enabled':'yes'}])
def test_profile_rejects_dangerous_or_invalid_shape(change):
    value=dict(preview_type='web',start_command=['npm','run','preview']);value.update(change)
    with pytest.raises(ValidationError): PreviewProfileInput.model_validate(value)

def test_profile_persistence_validation_revision_and_origin(bridge):
    client=bridge[0];project=bridge[4][0]['id'];url=f'/projects/{project}/preview-profile'
    assert client.get(url).json()['preview_type']=='none'
    store,fake,profile=configured(bridge)
    assert profile['revision']==1 and profile['id']
    assert client.put(url,json=dict(preview_type='none',revision=0)).status_code==409
    body=PreviewProfileInput(preview_type='none',revision=1).model_dump(mode='json')
    assert client.post(url+'/validate',json=body).json()['valid']
    assert client.put(url,json=body,headers={'Origin':'http://evil.test'}).status_code==403
    assert client.put(url,content='{"environment":{"NODE_ENV":"a","NODE_ENV":"b"}}',headers={'Content-Type':'application/json'}).status_code==422
    assert client.get(f'/projects/{uuid4()}/preview-profile').status_code==404
    reopened=TaskStore(str(bridge[2].engine.url.render_as_string(hide_password=False)))
    try:
        with TestClient(create_platform_app(bridge[7],reopened)) as other: assert other.get(url).json()==profile
    finally:reopened.close()

def test_eligibility_and_nonpreviewable_projects(bridge):
    store,fake,profile=configured(bridge)
    task=first(bridge)
    initial=bridge[0].get(f'/engineering-tasks/{task.id}/preview').json()
    assert not initial['can_start']
    assert bridge[0].post(f'/engineering-tasks/{task.id}/preview',json=dict(revision=task.revision,execution_task_id=str(uuid4()))).status_code==409
    result,*_=success(bridge)
    assert store.snapshot(task.id)['can_start']
    for phase in ('failed','cancelled'):
        with bridge[2].engine.begin() as db: db.execute(update(tasks).where(tasks.c.id==result['execution']['id']).values(phase=phase))
        assert request_preview(bridge,result).status_code==409
    with bridge[2].engine.begin() as db: db.execute(update(tasks).where(tasks.c.id==result['execution']['id']).values(phase='succeeded'))
    for values in ({'enabled':False},{'preview_type':'none'},{'requires_external_services':True}):
        latest=store.profile(bridge[4][0]['id']);body={k:latest[k] for k in PreviewProfileInput.model_fields};body.update(values)
        store.save_profile(bridge[4][0]['id'],PreviewProfileInput.model_validate(body))
        assert not store.snapshot(task.id)['can_start']
        assert request_preview(bridge,result).status_code==409

def test_duplicate_start_race_one_attempt_and_preview_capacity(bridge):
    result,*_=success(bridge);store,fake,profile=configured(bridge);gate=Barrier(2)
    def run(_):gate.wait();return request_preview(bridge,result)
    with ThreadPoolExecutor(max_workers=2) as pool: responses=list(pool.map(run,range(2)))
    assert all(r.status_code==202 for r in responses)
    assert responses[0].json()['id']==responses[1].json()['id']
    assert len(store.snapshot(first(bridge).id)['history'])==1
    store.config=store.config.model_copy(update={'max_active_previews':1})
    # Separate successful task, without creating another fake active AI execution.
    other=bridge[3].latest(bridge[4][0]['id']).plan.tasks[1]
    other_start=start(bridge,other);worker,*_=worker_for(bridge);worker.run_once()
    job=bridge[2].get(other_start.json()['execution']['id'])
    assert bridge[0].post(f"/tasks/{job['id']}/approve",json=dict(approval_id=job['approval'],run_tests=True,test_backend='local',framework='unittest',max_attempts=1)).status_code==202
    worker.run_once();worker.run_once()
    other_result=bridge[0].get(f'/engineering-tasks/{other.id}/execution').json()
    assert request_preview(bridge,other_result).status_code==409
    assert bridge[0].get(f"/workspace/members/{bridge[5]['id']}/capacity").json()['active_execution_count']==0

def test_ready_health_failure_stop_restart_and_history(bridge):
    result,*_=success(bridge);store,fake,profile=configured(bridge)
    preview=request_preview(bridge,result).json();assert preview['status']=='queued' and preview['preview_url'] is None
    fake.health=False;assert store.run_once('fixture')
    failed=store.get(preview['id']);assert failed['status']=='failed' and failed['preview_url'] is None
    assert fake.cleaned and bridge[2].get(result['execution']['id'])['phase']=='succeeded' and bridge[3].task(first(bridge).id).status=='review'
    fake.health=True
    response=bridge[0].post(f"/previews/{preview['id']}/restart",json=dict(revision=result['task']['revision'],execution_task_id=result['execution']['id']))
    assert response.status_code==202;new=response.json();assert new['id']!=preview['id']
    store.run_once('fixture');ready=store.get(new['id']);assert ready['status']=='ready' and ready['preview_url']=='http://127.0.0.1:49000/'
    assert bridge[0].post(f"/previews/{new['id']}/stop").json()['status']=='stopping'
    assert store.get(new['id'])['preview_url'] is None
    store.reconcile();assert store.get(new['id'])['status']=='stopped'
    assert store.get(new['id'])['stopped_at'] and len(store.snapshot(first(bridge).id)['history'])==2

@pytest.mark.parametrize('action',['accept','request-changes'])
def test_human_action_stops_preview_without_modifying_evidence_or_delivery(bridge,action):
    result,*_=success(bridge);store,fake,profile=configured(bridge);preview=request_preview(bridge,result).json();store.run_once('fixture')
    original_evidence=result['acceptance_evidence'];body=dict(revision=result['task']['revision'],execution_task_id=result['execution']['id'])
    if action=='accept':body.update(evidence_version=original_evidence['version'],unresolved_acknowledged=True)
    else:body['feedback']='Keep greeting and adjust details.'
    if action=='accept':
        assert bridge[0].post(f"/engineering-tasks/{result['task']['id']}/accept",json=body).status_code==409
        store.stop(preview['id']);store.reconcile()
    response=bridge[0].post(f"/engineering-tasks/{result['task']['id']}/{action}",json=body);assert response.status_code in (200,202),response.text
    assert store.get(preview['id'])['status']==('stopped' if action=='accept' else 'stopping');store.reconcile();assert store.get(preview['id'])['status']=='stopped'
    historical=bridge[0].get(f"/tasks/{result['execution']['id']}/acceptance-evidence").json()
    assert historical['criteria']==original_evidence['criteria'] and historical['version']==original_evidence['version']
    assert bridge[2].get(result['execution']['id'])['delivery']=={}
    assert bridge[0].post(f"/previews/{preview['id']}/restart",json=body if action=='accept' else {k:v for k,v in body.items() if k!='feedback'}).status_code in (409,422)

def test_ttl_startup_interruption_missing_container_and_reopen(bridge):
    result,*_=success(bridge);store,fake,profile=configured(bridge);preview=request_preview(bridge,result).json()
    with bridge[2].engine.begin() as db:db.execute(update(execution_previews).where(execution_previews.c.id==preview['id']).values(expires_at='2000-01-01T00:00:00+00:00'))
    store.reconcile();assert store.get(preview['id'])['status']=='expired'
    next_preview=request_preview(bridge,result).json()
    with bridge[2].engine.begin() as db:db.execute(update(execution_previews).where(execution_previews.c.id==next_preview['id']).values(status='building',owner='dead',lease=time.time()-1))
    store.reconcile();assert store.get(next_preview['id'])['status']=='failed'
    third=request_preview(bridge,result).json();store.run_once('fixture');fake.running.pop(third['id'])
    restored=PreviewStore(store.bridge,fake);restored.reconcile();restored.reconcile();assert restored.get(third['id'])['status']=='failed'

def test_stop_during_startup_cannot_promote_ready(bridge):
    result,*_=success(bridge);store,fake,profile=configured(bridge);preview=request_preview(bridge,result).json()
    fake.hook=lambda:store.stop(preview['id'])
    store.run_once('fixture');assert store.get(preview['id'])['status']=='stopped' and preview['id'] in fake.cleaned

def test_materialization_filters_secrets_and_preserves_original_and_receipt(bridge):
    source=Path(bridge[4][0]['path']);(source/'.env').write_text('PRIVATE=do-not-copy')
    result,*_=success(bridge)
    state=WorkflowState.model_validate(result['execution']['snapshot']);canonical=Path(state.workspace_path)
    (canonical/'.env').write_text('PRIVATE=do-not-copy')
    runtime=DockerPreviewRuntime(bridge[7]);before=receipt(state,bridge[7].workspace_root)
    archive,digest=runtime.archive(result['execution']['snapshot'])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        assert '.env' not in tar.getnames() and '.git' not in tar.getnames()
        assert "name.strip()" in tar.extractfile('app.py').read().decode()
        assert all(member.uid==10001 for member in tar.getmembers())
    assert len(digest)==64 and receipt(state,bridge[7].workspace_root)==before
    assert 'name.strip()' not in (source/'app.py').read_text()

def test_missing_or_tampered_workspace_refuses_preview(bridge):
    result,*_=success(bridge);store,fake,profile=configured(bridge)
    workspace=Path(result['execution']['snapshot']['workspace_path']);(workspace/'app.py').write_text('tampered')
    assert request_preview(bridge,result).status_code==409

def test_seccomp_restricts_outbound_without_disabling_default_deny():
    policy=json.loads(Path('containers/preview-seccomp.json').read_text(encoding='utf-8-sig'))
    assert policy['defaultAction']=='SCMP_ACT_ERRNO'
    allowed={name for rule in policy['syscalls'] if rule['action']=='SCMP_ACT_ALLOW' for name in rule['names']}
    assert 'connect' not in allowed and 'socketcall' not in allowed
    assert 'sendmsg' not in allowed and 'sendmmsg' not in allowed
    sendto=next(rule for rule in policy['syscalls'] if 'sendto' in rule['names'])
    assert sendto['args']==[{'index':2,'value':536870912,'valueTwo':0,'op':'SCMP_CMP_MASKED_EQ'}]
    assert {'accept','accept4','bind','listen'}<=allowed
    assert all(rule.get('args') for rule in policy['syscalls'] if 'socket' in rule['names'])

def test_cleanup_failure_remains_tracked_and_blocks_acceptance(bridge):
    result,*_=success(bridge);store,fake,profile=configured(bridge);preview=request_preview(bridge,result).json();store.run_once('fixture')
    def fail_cleanup(row):raise PreviewRuntimeError('Explicit cleanup failure')
    fake.cleanup=fail_cleanup;store.stop(preview['id']);store.reconcile()
    pending=store.get(preview['id']);assert pending['status']=='stopping' and 'Cleanup pending' in pending['failure_reason']
    assert pending['preview_url'] is None
    response=bridge[0].post(f"/engineering-tasks/{result['task']['id']}/accept",json=dict(revision=result['task']['revision'],execution_task_id=result['execution']['id'],evidence_version=result['acceptance_evidence']['version'],unresolved_acknowledged=True))
    assert response.status_code==409 and bridge[3].task(first(bridge).id).status=='review'

def test_adapter_refuses_foreign_resource_ownership(bridge):
    runtime=DockerPreviewRuntime(bridge[7]);row=dict(id=str(uuid4()),execution_task_id=str(uuid4()),run_id=str(uuid4()))
    runtime.inspect=lambda name,kind='container':{'Config':{'Labels':{'codeops.workspace':'another-workspace'}}}
    with pytest.raises(PreviewRuntimeError,match='ownership'):runtime.resource(row,'container','unrelated')
    flags=runtime.restrictions(row,'private-network',runtime=True)
    assert not any('type=bind' in flag for flag in flags)
    assert '--cap-drop=ALL' in flags and '--read-only' in flags and '--user=10001:10001' in flags
    assert '--network' in flags and 'host' not in flags

def test_ownership_namespace_is_path_specific_and_not_password_specific(tmp_path):
    from autonomous_engineering.core.config import Settings
    one=Settings(_env_file=None,database_url='postgresql+psycopg://user:one@localhost/codeops',workspace_root=tmp_path/'one')
    rotated=Settings(_env_file=None,database_url='postgresql+psycopg://user:two@localhost/codeops',workspace_root=tmp_path/'one')
    other=Settings(_env_file=None,database_url='postgresql+psycopg://user:one@localhost/codeops',workspace_root=tmp_path/'two')
    assert DockerPreviewRuntime(one).workspace_key==DockerPreviewRuntime(rotated).workspace_key
    assert DockerPreviewRuntime(one).workspace_key!=DockerPreviewRuntime(other).workspace_key

def test_preview_lifecycle_does_not_invalidate_team_resource_revision(bridge):
    from autonomous_engineering.infrastructure.team_tables import workspace_state, team_revisions
    result,*_=success(bridge)
    with bridge[2].engine.connect() as db:
        before=(db.execute(select(workspace_state.c.revision)).scalar_one(),list(db.execute(select(team_revisions)).all()))
    store,fake,_=configured(bridge);preview=request_preview(bridge,result).json()
    store.run_once('fixture');store.reconcile();store.stop(preview['id']);store.reconcile()
    with bridge[2].engine.connect() as db:
        after=(db.execute(select(workspace_state.c.revision)).scalar_one(),list(db.execute(select(team_revisions)).all()))
    assert before==after

@pytest.mark.skipif(not os.environ.get('ASE_INTEGRATION_PREVIEWS'),reason='Explicit Docker ownership reconciliation opt-in')
def test_real_reconciliation_cleans_owned_orphan_and_leaves_unrelated_container(bridge):
    store=bridge[1].state.preview_store
    runtime=DockerPreviewRuntime(bridge[7].model_copy(update={'docker_executable':os.environ.get('ASE_DOCKER_EXECUTABLE','docker')}));store.runtime=runtime
    row=dict(id=str(uuid4()),execution_task_id=str(uuid4()),run_id=str(uuid4()))
    own=runtime.names(row)[0];unrelated='unrelated-preview-fixture-'+uuid4().hex
    runtime.docker('create','--name',own,*runtime.label_args(row),runtime.config.preview_python_image,'build',PreviewProfileInput().model_dump_json())
    runtime.docker('create','--name',unrelated,'--label','codeops.workspace=another-workspace',runtime.config.preview_python_image,'build',PreviewProfileInput().model_dump_json())
    try:
        store.reconcile()
        assert runtime.inspect(own) is None and runtime.inspect(unrelated) is not None
    finally:
        if runtime.inspect(own):runtime.docker('rm','-f',own)
        if runtime.inspect(unrelated):runtime.docker('rm','-f',unrelated)

@pytest.mark.skipif(not os.environ.get('ASE_INTEGRATION_PREVIEWS'),reason='Explicit real Docker preview opt-in')
@pytest.mark.parametrize('runtime_name',['python','node'])
def test_real_docker_loopback_health_isolation_network_logs_and_cleanup(bridge,runtime_name):
    source=Path(bridge[4][0]['path']);(source/'index.html').write_text('<html><body>Hello preview</body></html>')
    if runtime_name=='node':
        (source/'server.mjs').write_text("import http from 'node:http';import fs from 'node:fs';fs.writeFileSync('runtime-cache','isolated');http.createServer((q,r)=>r.end('Hello preview')).listen(8000,'0.0.0.0');")
        (source/'package.json').write_text(json.dumps({'name':'fixture','version':'1.0.0','scripts':{'build':'node -e "require(\'fs\').writeFileSync(\'built\',\'inside\')"'}}))
        (source/'package-lock.json').write_text(json.dumps({'name':'fixture','version':'1.0.0','lockfileVersion':3,'packages':{'':{'name':'fixture','version':'1.0.0'}}}))
    result,*_=success(bridge);store,fake,profile=configured(bridge)
    saved=store.profile(bridge[4][0]['id']);data={k:saved[k] for k in PreviewProfileInput.model_fields}
    data.update(runtime=runtime_name,start_command=['node','server.mjs'] if runtime_name=='node' else ['python','-m','http.server','8000','--bind','0.0.0.0'],build_commands=[['npm','run','build']] if runtime_name=='node' else [],timeout_seconds=30)
    store.save_profile(bridge[4][0]['id'],PreviewProfileInput.model_validate(data))
    settings=bridge[7].model_copy(update={'docker_executable':os.environ.get('ASE_DOCKER_EXECUTABLE','docker')})
    actual=DockerPreviewRuntime(settings);store.runtime=actual
    state=WorkflowState.model_validate(result['execution']['snapshot']);before=receipt(state,settings.workspace_root)
    preview=request_preview(bridge,result).json()
    try:
        assert store.run_once('real-docker')
        ready=store.get(preview['id']);assert ready['status']=='ready',ready
        with urllib.request.urlopen(ready['preview_url'],timeout=3) as page: assert 'Hello preview' in page.read().decode()
        with bridge[2].engine.connect() as db: row=dict(db.execute(select(execution_previews).where(execution_previews.c.id==preview['id'])).mappings().one())
        info=actual.resource(row,'container',actual.names(row)[1])
        assert info['Config']['Labels']['codeops.execution_id']==result['execution']['id']
        assert info['Config']['User']=='10001:10001'
        assert info['HostConfig']['ReadonlyRootfs'] and info['HostConfig']['CapDrop']==['ALL']
        assert info['HostConfig']['Memory']==1073741824 and info['HostConfig']['PidsLimit']==256
        assert info['NetworkSettings']['Ports']['8000/tcp'][0]['HostIp']=='127.0.0.1'
        assert ready['host_port']!=8000 and 1<=ready['host_port']<=65535
        assert not any(value.startswith(('ASE_','GITHUB_TOKEN=','AWS_','SSH_')) for value in info['Config']['Env'])
        assert all(m['Type']!='bind' for m in info['Mounts'])
        probe=['python','-c',"import socket; s=socket.socket(); print(s.connect_ex(('1.1.1.1',443)))"] if runtime_name=='python' else ['node','-e',"require('net').connect(443,'1.1.1.1').on('error',e=>console.log(e.code))"]
        outbound=actual.docker('exec',actual.names(row)[1],*probe)
        assert (outbound=='1' if runtime_name=='python' else 'EPERM' in outbound)
        assert receipt(state,settings.workspace_root)==before
        assert not (Path(state.workspace_path)/'runtime-cache').exists() and not (source/'runtime-cache').exists()
        assert 'name.strip()' not in (source/'app.py').read_text()
        store.reconcile();assert len(store.get(preview['id'])['logs'])<=16384
        store.stop(preview['id']);store.reconcile();assert store.get(preview['id'])['status']=='stopped'
        assert actual.resource(row,'container',actual.names(row)[1]) is None
        # Artifact acceptance continues to work after runtime writes in the separate volume.
        accepted=bridge[0].post(f"/engineering-tasks/{result['task']['id']}/accept",json=dict(revision=result['task']['revision'],execution_task_id=result['execution']['id'],evidence_version=result['acceptance_evidence']['version'],unresolved_acknowledged=True))
        assert accepted.status_code==200,accepted.text
    finally:
        store.stop(preview['id']);store.reconcile()

@pytest.mark.skipif(not os.environ.get('ASE_INTEGRATION_PREVIEWS'),reason='Explicit real Docker framework preview opt-in')
@pytest.mark.parametrize('framework',['vite','fastapi'])
def test_real_vite_and_fastapi_profiles(bridge,framework):
    source=Path(bridge[4][0]['path'])
    if framework=='vite':
        (source/'index.html').write_text('<!doctype html><html><body><h1>Hello preview</h1></body></html>')
        (source/'package.json').write_text(json.dumps({'name':'preview-vite-fixture','version':'1.0.0','type':'module','scripts':{'build':'vite build','preview':'vite preview'},'devDependencies':{'vite':'7.3.6'}}))
        (source/'package-lock.json').write_bytes(Path('tests/fixtures/preview-vite-package-lock.json').read_bytes())
    else:
        (source/'requirements.txt').write_text('fastapi==0.115.0\nuvicorn==0.30.6\n')
        (source/'preview_api.py').write_text("from fastapi import FastAPI\nfrom app import greet\napp=FastAPI()\n@app.get('/health')\ndef health(): return {'greeting':greet(' Ada ')}\n")
    result,*_=success(bridge);store,fake,_=configured(bridge)
    profile=store.profile(bridge[4][0]['id']);data={key:profile[key] for key in PreviewProfileInput.model_fields}
    data.update(preview_type='web' if framework=='vite' else 'api',runtime='node' if framework=='vite' else 'python',
        build_commands=[['npm','run','build']] if framework=='vite' else [],build_network=True,timeout_seconds=120,
        start_command=['npm','run','preview','--','--host','0.0.0.0','--port','8000'] if framework=='vite' else ['uvicorn','preview_api:app','--host','0.0.0.0','--port','8000'],
        health_path='/' if framework=='vite' else '/health',open_path='/' if framework=='vite' else '/docs')
    store.save_profile(bridge[4][0]['id'],PreviewProfileInput.model_validate(data))
    actual=DockerPreviewRuntime(bridge[7].model_copy(update={'docker_executable':os.environ.get('ASE_DOCKER_EXECUTABLE','docker')}));store.runtime=actual
    preview=request_preview(bridge,result).json()
    try:
        store.run_once('real-framework');ready=store.get(preview['id']);assert ready['status']=='ready',ready
        with urllib.request.urlopen(ready['preview_url'],timeout=3) as page:
            text=page.read().decode();assert ('Hello preview' if framework=='vite' else 'Swagger UI') in text
        if framework=='fastapi':
            with urllib.request.urlopen(ready['base_url']+'/health') as page:assert json.load(page)['greeting']=='Hello Ada'
    finally:store.stop(preview['id']);store.reconcile()
