"""Provider settings persist safely and drive real gateway protocol requests."""
import json
import os
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, create_engine, text
from sqlalchemy.engine import make_url
from uuid import uuid4

from autonomous_engineering.core.config import Settings
from autonomous_engineering.domain.models import ProviderBadRequest, ProviderResponseError, ProviderUnavailable, ProviderAuthenticationError
from autonomous_engineering.infrastructure.custom_models import ConfiguredProvider, validate_endpoint, vetted_addresses
from autonomous_engineering.infrastructure.model_settings import ConnectionInput, RouteInput, attach_model_settings, connections, SettingsConflict
from autonomous_engineering.infrastructure.model_gateway import ModelGateway, resolve_route, model_configured
from autonomous_engineering.infrastructure.task_store import TaskStore
from autonomous_engineering.platform import create_platform_app
from autonomous_engineering.application.worker import Worker
from test_model_gateway import request, Transport, completion

KEY = 'DO_NOT_RETURN_THIS_TEST_KEY'


@pytest.fixture(params=['sqlite', 'postgresql'])
def system(tmp_path, request):
    root = schema = None
    url = 'sqlite:///'+str(tmp_path/'models.db')
    if request.param == 'postgresql':
        if not os.environ.get('ASE_INTEGRATION_DATABASE_URL'): pytest.skip('Explicit PostgreSQL integration opt-in')
        root = create_engine(os.environ['ASE_INTEGRATION_DATABASE_URL'])
        schema = 'models_'+uuid4().hex
        with root.begin() as db: db.execute(text('CREATE SCHEMA '+schema))
        url = make_url(os.environ['ASE_INTEGRATION_DATABASE_URL']).update_query_dict({'options':'-csearch_path='+schema}).render_as_string(hide_password=False)
    settings = Settings(_env_file=None, database_url=url, workspace_root=tmp_path/'work', ollama_model='legacy-model')
    tasks = TaskStore(settings.database_url.get_secret_value())
    saved = attach_model_settings(settings, tasks.engine)
    yield settings, tasks, saved
    tasks.close()
    if root:
        with root.begin() as db: db.execute(text('DROP SCHEMA '+schema+' CASCADE'))
        root.dispose()


def connection(saved, **kwargs):
    return saved.save(ConnectionInput(name='Test provider', protocol='openai', base_url='https://api.example.com/v1', api_key=KEY, **kwargs))


def route(saved, primary, model='custom-model', **kwargs):
    return saved.set_route(RouteInput(revision=saved.snapshot()['revision'], primary_connection=primary['id'], primary_model=model, **kwargs))


def test_encrypted_persistence_and_revision(system):
    settings, tasks, saved = system
    first = connection(saved)
    assert first['has_key'] and KEY not in json.dumps(saved.snapshot())
    with tasks.engine.connect() as db:
        row = db.execute(select(connections)).mappings().one()
        assert KEY not in row['encrypted_key'] and KEY not in row['profile']
        assert row['encrypted_key'].startswith('gAAAA')
    assert saved.profile(first['id'], secrets=True)['key'] == KEY
    payload = ConnectionInput(**{k:v for k,v in first.items() if k not in ('id','has_key')})
    second = saved.save(payload, first['id'])
    assert second['revision'] == 2 and saved.profile(first['id'], secrets=True)['key'] == KEY
    with pytest.raises(SettingsConflict): saved.save(payload, first['id'])
    saved.save(payload.model_copy(update={'revision':2, 'clear_key':True}), first['id'])
    assert saved.profile(first['id'], secrets=True)['key'] is None
    assert len(list((settings.workspace_root/'model-credentials').glob('*.key'))) == 1


def test_route_lifecycle_and_no_restart(system):
    settings, tasks, saved = system
    primary = connection(saved)
    route(saved, primary)
    old_gateway = ModelGateway(settings)
    assert old_gateway.route.model == 'custom-model' and model_configured(settings)
    second_settings = Settings(_env_file=None, database_url=settings.database_url, workspace_root=settings.workspace_root, ollama_model='legacy-model')
    worker = Worker(second_settings, tasks)
    assert ModelGateway(worker.config).route.model == 'custom-model'
    route(saved, primary, model='changed-model')
    assert ModelGateway(worker.config).route.model == 'changed-model'
    assert old_gateway.route.model == 'custom-model'
    assert ModelGateway(worker.config).providers[primary['id']].key == KEY
    with pytest.raises(ValueError, match='another route'): saved.remove(primary['id'], primary['revision'])
    with pytest.raises(SettingsConflict): saved.set_route(revision=1)
    saved.set_route(revision=saved.snapshot()['revision'])
    assert resolve_route(worker.config).provider == 'ollama'
    saved.remove(primary['id'], primary['revision'])
    assert saved.snapshot()['connections'] == []


def test_environment_lock(system):
    settings, _, saved = system
    primary = connection(saved)
    route(saved, primary)
    settings.model_settings_locked = True
    assert resolve_route(settings).model == 'legacy-model'
    assert saved.snapshot()['locked']
    with pytest.raises(ValueError, match='locked'): connection(saved)


@pytest.mark.parametrize('url', ['http://example.com/v1', 'https://169.254.169.254/', 'https://10.0.0.1/v1', 'https://[fe80::1]/', 'https://user:password@api.example.com/v1', 'https://example.com/v1?key=secret', 'https://example.com/#fragment', 'http://localhost:70000', 'https://example.com/\nsecret'])
def test_endpoint_rejections(url):
    with pytest.raises(ValueError): validate_endpoint(url)


@pytest.mark.parametrize('url', ['https://api.example.com/v1', 'http://127.0.0.1:11434', 'http://localhost:8080/v1', 'https://[::1]:444/v1'])
def test_supported_endpoints(url): assert validate_endpoint(url) == url


def test_dns_private_destination_rejected(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('10.0.0.1',443))])
    with pytest.raises(ProviderBadRequest): vetted_addresses('rebound.example.com', 443)
    with pytest.raises(ProviderBadRequest): vetted_addresses('localhost', 443)


@pytest.mark.parametrize('protocol,payload,expected_path', [
    ('openai',completion(),'/chat/completions'),
    ('anthropic',{'stop_reason':'end_turn','content':[{'type':'text','text':'{"answer":"ok"}'}],'usage':{'input_tokens':12,'output_tokens':7}},'/messages'),
    ('gemini',{'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'PRIVATE_THOUGHT','thought':True},{'text':'{"answer":"ok"}'}]}}], 'usageMetadata':{'promptTokenCount':12,'candidatesTokenCount':7}},'/models/custom%2Fmodel:generateContent'),
])
def test_protocol_translation(system, protocol, payload, expected_path):
    _,_,saved=system
    profile=connection(saved)
    profile=saved.profile(profile['id'], secrets=True)
    profile.update(protocol=protocol,token_parameter='max_completion_tokens',send_temperature=False)
    transport=Transport((200,payload,'request-1'))
    response=ConfiguredProvider(profile,transport).generate(request().model_copy(update={'model':'custom/model'}))
    url,body,_,headers=transport.calls[0]
    assert url.endswith(expected_path) and 'temperature' not in body
    assert response.content=='{"answer":"ok"}' and response.input_tokens==12 and response.output_tokens==7
    if protocol=='openai':
        assert body['max_completion_tokens']==128 and 'max_tokens' not in body
        assert headers['Authorization']=='Bearer '+KEY
    elif protocol=='anthropic':
        assert body['system'] and all(m['role']!='system' for m in body['messages'])
        assert headers['x-api-key']==KEY and headers['anthropic-version']=='2023-06-01'
    else:
        assert body['systemInstruction'] and body['generationConfig']['maxOutputTokens']==128
        assert headers['x-goog-api-key']==KEY and KEY not in url


@pytest.mark.parametrize('protocol,payload', [('openai',{'choices':[{'finish_reason':'length','message':{'content':'{}'}}]}), ('anthropic',{'stop_reason':'max_tokens','content':[{'type':'text','text':'{}'}]}), ('gemini',{'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'{}'}]}}]})])
def test_truncated_results_rejected(system, protocol, payload):
    _,_,saved=system
    profile=saved.profile(connection(saved)['id'], secrets=True);profile['protocol']=protocol
    with pytest.raises(ProviderResponseError): ConfiguredProvider(profile,Transport((200,payload,None))).generate(request())


def test_same_protocol_fallback_and_traces(system, monkeypatch):
    settings,_,saved=system
    primary=connection(saved); fallback=connection(saved)
    route(saved,primary,fallback_enabled=True,fallback_connection=fallback['id'],fallback_model='backup-model')
    calls=[]
    def generate(self, req):
        calls.append((self.profile['id'],req.model))
        if self.profile['id']==primary['id']: raise ProviderUnavailable('openai','Unavailable')
        from autonomous_engineering.domain.models import ModelResponse
        return ModelResponse(provider='openai',model=req.model,content='{}')
    monkeypatch.setattr(ConfiguredProvider,'generate',generate)
    records=[]
    assert ModelGateway(settings).generate(request(),records.append).model=='backup-model'
    assert calls==[(primary['id'],'custom-model'),(fallback['id'],'backup-model')]
    assert records[1].fallback_used and records[1].provider=='openai' and records[1].provider_name=='Test provider'
    monkeypatch.setattr(ConfiguredProvider,'generate',lambda *a:(_ for _ in ()).throw(ProviderAuthenticationError('openai','Authentication failed')))
    records=[]
    with pytest.raises(ProviderAuthenticationError): ModelGateway(settings).generate(request(),records.append)
    assert len(records)==1


def test_settings_api_secret_safety_and_origin(system):
    settings,tasks,_=system
    client=TestClient(create_platform_app(settings,tasks))
    body={'name':'Cloud','protocol':'openai','base_url':'https://api.example.com/v1','api_key':KEY}
    response=client.post('/system/models/connections',json=body)
    assert response.status_code==201 and KEY not in response.text
    connection_id=response.json()['id']
    assert KEY not in client.get('/system/models/settings').text
    invalid=client.post('/system/models/connections',json={**body,'api_key':KEY+'\n'})
    assert invalid.status_code==422 and KEY not in invalid.text
    extra=client.post('/system/models/connections',json={**body,'unexpected':KEY})
    assert extra.status_code==422 and KEY not in extra.text
    assert client.post('/system/models/connections',json=body,headers={'Origin':'https://evil.example'}).status_code==403
    assert client.post('/system/models/connections',json=body,headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
    assert client.post('/system/models/connections',content=json.dumps(body),headers={'Content-Type':'text/plain'}).status_code==415
    assert client.post('/system/models/connections',content='{"api_key":"'+KEY+'","api_key":"'+KEY+'"}',headers={'Content-Type':'application/json'}).status_code==422
    response=client.put('/system/models/route',json={'revision':1,'primary_connection':connection_id,'primary_model':'custom-model'})
    assert response.status_code==200
    assert client.get('/system/models').json()['primary']['display_name']=='Cloud'
    assert client.put('/system/models/route',json={'revision':1,'primary_connection':connection_id,'primary_model':'stale'}).status_code==409
    assert client.delete(f'/system/models/connections/{connection_id}?revision=1').status_code==422
    assert client.delete('/system/models/route?revision=2').status_code==200
    assert client.delete(f'/system/models/connections/{connection_id}?revision=1').status_code==200


def test_real_local_protocol_request_and_no_redirect(system):
    settings,_,saved=system
    received=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            if self.path.startswith('/redirect'):
                self.send_response(302);self.send_header('Location','http://169.254.169.254/');self.end_headers();return
            self.send_response(200);self.end_headers();self.wfile.write(json.dumps({'data':[{'id':'fixture-model'}]}).encode())
        def do_POST(self):
            received.append((self.path,json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            self.send_response(200);self.end_headers();self.wfile.write(json.dumps(completion()).encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        base=f'http://127.0.0.1:{server.server_port}/v1'
        profile=saved.save(ConnectionInput(name='Local compatible',protocol='openai',base_url=base))
        route(saved,profile,model='fixture-model')
        provider=ModelGateway(settings).providers[profile['id']]
        assert provider.catalog()==['fixture-model']
        assert ModelGateway(settings).generate(request()).content=='{"answer":"ok"}'
        assert received[0][0]=='/v1/chat/completions' and received[0][1]['model']=='fixture-model'
        provider.url=f'http://127.0.0.1:{server.server_port}/redirect'
        with pytest.raises(ProviderBadRequest): provider.catalog()
    finally: server.shutdown();server.server_close();thread.join()


def test_route_requires_keys_and_valid_fallback(system):
    _,_,saved=system
    p=saved.save(ConnectionInput(name='Cloud',protocol='openai',base_url='https://api.example.com/v1'))
    with pytest.raises(ValueError,match='API key'): route(saved,p)
    p=connection(saved)
    with pytest.raises(ValueError,match='fallback'): route(saved,p,fallback_enabled=True)
    with pytest.raises(ValueError,match='different'): route(saved,p,fallback_enabled=True,fallback_connection=p['id'],fallback_model='custom-model')


def test_route_selection_and_deletion_race(system):
    _, _, saved = system
    for _ in range(4):
        primary = connection(saved)
        barrier = threading.Barrier(2)
        revision = saved.snapshot()['revision']
        def apply():
            barrier.wait()
            try: saved.set_route(RouteInput(revision=revision, primary_connection=primary['id'], primary_model='custom-model'))
            except ValueError: pass
        def remove():
            barrier.wait()
            try: saved.remove(primary['id'], primary['revision'])
            except ValueError: pass
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(apply), pool.submit(remove)]
            for result in results: result.result(timeout=10)
        state = saved.snapshot()
        if state['route']:
            assert state['route']['primary_connection'] in {p['id'] for p in state['connections']}
            saved.set_route(revision=state['revision'])


@pytest.mark.parametrize('protocol,payload', [
    ('nvidia', completion()),
    ('ollama', {'done':True,'message':{'content':'{"answer":"ok"}'},'eval_count':7}),
])
def test_saved_native_protocol_uses_selected_credentials(system, protocol, payload):
    _, _, saved = system
    profile = {'id':'native','name':'Native connection','protocol':protocol,
        'base_url':'https://integrate.api.nvidia.com/v1' if protocol == 'nvidia' else 'http://127.0.0.1:11434',
        'key':KEY if protocol == 'nvidia' else None, 'structured_mode':'prompt'}
    transport = Transport((200,payload,None))
    response = ConfiguredProvider(profile,transport).generate(request())
    assert response.content == '{"answer":"ok"}' and response.provider == protocol
    if protocol == 'nvidia': assert transport.calls[0][3]['Authorization'] == 'Bearer '+KEY
    else: assert transport.calls[0][0].endswith('/api/chat') and transport.calls[0][1]['format'] == request().structured_schema
