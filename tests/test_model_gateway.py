"""No real cloud requests: mocked NVIDIA transport and local Ollama HTTP fixtures."""
import io
import json
from urllib.error import HTTPError, URLError
from uuid import uuid4
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from autonomous_engineering.core.config import Settings
from autonomous_engineering.domain.models import (
    ModelRequest, ModelMessage, ModelResponse, ProviderUnavailable, ProviderTimeout,
    ProviderRateLimited, ProviderAuthenticationError, ProviderBadRequest, ProviderResponseError,
    ProviderNotConfigured, CombinedProviderError,
)
from autonomous_engineering.infrastructure.model_gateway import ModelGateway, resolve_route, model_configured, KIMI_MODEL
from autonomous_engineering.infrastructure.model_providers import NvidiaNimProvider, OllamaProvider, HttpTransport
from autonomous_engineering.infrastructure.model_planner import GatewayPlanProvider
from autonomous_engineering.infrastructure.model_product import GatewayProductPlanProvider
from autonomous_engineering.infrastructure.model_developer import GatewayDevelopmentProvider
from autonomous_engineering.infrastructure.model_reviewer import GatewayReviewProvider
from autonomous_engineering.infrastructure.model_evidence import GatewayEvidenceProvider
from autonomous_engineering.infrastructure.task_store import TaskStore
from autonomous_engineering.infrastructure.planning_store import PlanningStore
from autonomous_engineering.platform import create_platform_app
from autonomous_engineering.agents.planner import Planner, PlanningError
from autonomous_engineering.agents.product_planner import ProductPlanningAgent
from autonomous_engineering.agents.developer import Developer, approval_identity
from autonomous_engineering.agents.reviewer import Reviewer
from autonomous_engineering.domain.results import RepositoryAnalysis
from autonomous_engineering.domain.tasks import TaskRequest
from autonomous_engineering.domain.acceptance_evidence import EvidenceContext
from autonomous_engineering.application.acceptance_mapper import map_evidence
from autonomous_engineering.domain.previews import PreviewProfileInput
from autonomous_engineering.tools.repository import RepositoryReader
from test_planner import ollama_server, source
from test_developer import planned
from test_reviewer import developed
from test_product_planning import draft_data, product
from test_acceptance_evidence import criterion, source as evidence_source

KEY = 'PRIVATE_TEST_NVIDIA_KEY'


def config(**kwargs):
    return Settings(_env_file=None, **{'model_primary_provider':'nvidia', 'nvidia_api_key':KEY,
                                    'ollama_model':'fixture-local', **kwargs})


def request():
    return ModelRequest(purpose='development', model=KIMI_MODEL,
        messages=(ModelMessage(role='system',content='Return JSON per schema'), ModelMessage(role='user',content='Fixture task')),
        structured_schema={'type':'object','properties':{'answer':{'type':'string'}}},
        temperature=.2, max_output_tokens=128, context_tokens=16384, timeout_seconds=4)


class Spy:
    def __init__(self, *outcomes):
        self.requests = []
        self.outcomes = list(outcomes) or ['{}']
    def generate(self, req):
        self.requests.append(req)
        value = self.outcomes.pop(0) if len(self.outcomes)>1 else self.outcomes[0]
        if isinstance(value, Exception): raise value
        return ModelResponse(content=value, provider='nvidia' if req.model==KIMI_MODEL else 'ollama', model=req.model, input_tokens=10, output_tokens=5)


def gateway(primary, fallback=None, **kwargs):
    return ModelGateway(config(**kwargs), {'nvidia':primary,'ollama':fallback or Spy()})


class Transport:
    def __init__(self,*outcomes):
        self.calls = []
        self.outcomes = list(outcomes)
    def send(self, url, body, timeout, headers=None):
        self.calls.append((url,body,timeout,headers))
        value = self.outcomes.pop(0)
        if isinstance(value,Exception): raise value
        return value


def completion(content='{"answer":"ok"}', **kwargs):
    return {'choices':[{'message':{'content':content,'reasoning_content':'PRIVATE_REASONING'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':12,'completion_tokens':7,'total_tokens':19},**kwargs}


@pytest.mark.parametrize('mode',['prompt','json_object','json_schema'])
def test_nvidia_translation_and_usage(mode):
    transport=Transport((200,completion(),'request-id'))
    result=NvidiaNimProvider(config(nvidia_structured_mode=mode),transport).generate(request())
    url,body,timeout,headers=transport.calls[0]
    assert url=='https://integrate.api.nvidia.com/v1/chat/completions'
    assert headers['Authorization']=='Bearer '+KEY
    assert body['model']==KIMI_MODEL and body['max_tokens']==128 and body['stream'] is False
    assert body['temperature']==.2 and body['reasoning_effort']=='low' and timeout==4
    assert body['messages']==[m.model_dump() for m in request().messages]
    assert 'num_ctx' not in body
    if mode=='prompt': assert 'response_format' not in body
    elif mode=='json_schema': assert body['response_format']['json_schema']['schema']==request().structured_schema
    else: assert body['response_format']=={'type':'json_object'}
    assert result.content=='{"answer":"ok"}' and result.total_tokens==19 and result.request_id=='request-id'
    assert 'PRIVATE_REASONING' not in result.model_dump_json()


def test_pending_nvidia_result_is_polled_with_same_deadline(monkeypatch):
    monkeypatch.setattr('autonomous_engineering.infrastructure.model_providers.time.sleep',lambda _:None)
    rid=str(uuid4());transport=Transport((202,{},rid),(200,completion(),None))
    result=NvidiaNimProvider(config(),transport).generate(request())
    assert result.request_id==rid
    assert transport.calls[1][0].endswith('/status/'+rid)
    assert transport.calls[1][1] is None and transport.calls[1][2]<=4


@pytest.mark.parametrize('payload',[{}, {'choices':[]}, {'choices':[{'message':{'content':'{}'},'finish_reason':'length'}]},
    {'choices':[{'message':{'content':None},'finish_reason':'stop'}]}])
def test_incomplete_nvidia_response_does_not_fallback(payload):
    fallback=Spy();primary=NvidiaNimProvider(config(),Transport((200,payload,None)))
    with pytest.raises(ProviderResponseError):gateway(primary,fallback).generate(request())
    assert not fallback.requests


@pytest.mark.parametrize('status,error_type',[(401,ProviderAuthenticationError),(403,ProviderAuthenticationError),
    (400,ProviderBadRequest),(422,ProviderBadRequest),(429,ProviderRateLimited),
    (500,ProviderUnavailable),(502,ProviderUnavailable),(503,ProviderUnavailable),(504,ProviderUnavailable),
    (501,ProviderBadRequest),(302,ProviderBadRequest)])
def test_http_classification_and_secret_sanitization(status,error_type):
    class Broken:
        def open(self, req, timeout):
            assert req.headers['Authorization']=='Bearer '+KEY
            raise HTTPError(req.full_url,status,KEY,{'Authorization':KEY},io.BytesIO(KEY.encode()))
    with pytest.raises(error_type) as err:
        HttpTransport('nvidia',lambda:Broken()).send('https://integrate.api.nvidia.com/v1/chat/completions',{},1,{'Authorization':'Bearer '+KEY})
    assert KEY not in str(err.value) and err.value.__suppress_context__


@pytest.mark.parametrize('failure,error_type',[(TimeoutError(KEY),ProviderTimeout),(URLError(TimeoutError(KEY)),ProviderTimeout),
    (URLError(KEY),ProviderUnavailable),(ConnectionError(KEY),ProviderUnavailable)])
def test_connection_errors_are_typed_and_sanitized(failure,error_type):
    class Broken:
        def open(self,*args,**kwargs):raise failure
    with pytest.raises(error_type) as err:HttpTransport('nvidia',lambda:Broken()).send('https://integrate.api.nvidia.com/v1/chat/completions',{},1)
    assert KEY not in str(err.value)


def test_primary_success_is_one_call_no_fallback():
    primary,fallback=Spy(),Spy();observed=[]
    result=gateway(primary,fallback).generate(request(),observed.append)
    assert result.provider=='nvidia' and len(primary.requests)==1 and not fallback.requests
    assert len(observed)==1 and not observed[0].fallback_used


@pytest.mark.parametrize('error_type',[ProviderTimeout,ProviderUnavailable,ProviderRateLimited,ProviderNotConfigured])
def test_availability_fallback_preserves_logical_request(error_type):
    primary,fallback=Spy(error_type('nvidia','Fixture failure')),Spy();observed=[]
    result=gateway(primary,fallback).generate(request(),observed.append)
    assert result.provider=='ollama' and len(primary.requests)==len(fallback.requests)==1
    assert primary.requests[0].model_dump(exclude={'model'})==fallback.requests[0].model_dump(exclude={'model'})
    assert observed[1].fallback_used and observed[1].fallback_reason==error_type.reason
    assert observed[0].outcome==error_type.reason


@pytest.mark.parametrize('error_type',[ProviderAuthenticationError,ProviderBadRequest,ProviderResponseError])
def test_configuration_and_response_errors_never_fallback(error_type):
    fallback=Spy()
    with pytest.raises(error_type):gateway(Spy(error_type('nvidia','Fixture failure')),fallback).generate(request())
    assert not fallback.requests


def test_fallback_disabled_and_combined_failure_are_bounded():
    primary=Spy(ProviderTimeout('nvidia','Primary timed out'));fallback=Spy(ProviderUnavailable('ollama','Local service offline'));observed=[]
    with pytest.raises(CombinedProviderError) as err:gateway(primary,fallback).generate(request(),observed.append)
    assert len(primary.requests)==len(fallback.requests)==1 and len(observed)==2
    assert 'Primary nvidia' in str(err.value) and 'Fallback ollama' in str(err.value)
    with pytest.raises(ProviderTimeout):gateway(primary,fallback,model_fallback_enabled=False).generate(request())
    assert len(fallback.requests)==1


def test_ollama_contract_with_local_http_fixture(ollama_server):
    url,behavior,captured=ollama_server
    behavior['body']={'done':True,'message':{'content':'{"answer":"ok"}'},'prompt_eval_count':11,'eval_count':4}
    result=OllamaProvider(Settings(_env_file=None,ollama_base_url=url)).generate(request().model_copy(update={'model':'fixture'}))
    assert result.provider=='ollama' and result.input_tokens==11 and result.total_tokens is None
    assert captured[0][1]['format']==request().structured_schema
    assert captured[0][1]['options']=={'temperature':.2,'num_predict':128,'num_ctx':16384}


def test_coding_planner_uses_gateway_and_domain_validation(source):
    primary=Spy(json.dumps({'problem_interpretation':'Fixture','steps':[{'description':'Fix app','files':['app.py']}],'tests_to_run':['Check app']}))
    provider=GatewayPlanProvider(config(),gateway(primary))
    plan=Planner(provider).plan(RepositoryReader(source),TaskRequest(repository_path=str(source),user_request='Fix app'),RepositoryAnalysis(architecture_summary='Fixture',languages=[]))
    assert plan.steps and primary.requests[0].purpose=='coding_planning'
    assert str(source) not in primary.requests[0].messages[-1].content


def test_product_semantic_retry_stays_on_primary():
    invalid=draft_data();invalid['tasks'][0]['dependencies']=['T2']
    primary=Spy(json.dumps(invalid),json.dumps(draft_data()));fallback=Spy()
    result=ProductPlanningAgent(GatewayProductPlanProvider(config(),gateway(primary,fallback))).plan('Fixture',{'name':'Demo'})
    assert len(result.tasks)==2 and len(primary.requests)==2 and not fallback.requests
    assert 'validation_feedback' in primary.requests[1].messages[-1].content


@pytest.mark.parametrize('content',['not JSON','{}','[]'])
def test_invalid_business_output_never_switches_provider(content):
    primary,fallback=Spy(content),Spy()
    with pytest.raises(PlanningError):ProductPlanningAgent(GatewayProductPlanProvider(config(),gateway(primary,fallback))).plan('Fixture',{'name':'Demo'})
    assert len(primary.requests)==2 and not fallback.requests


def test_developer_gateway_preserves_approval_and_snapshot(planned):
    state,storage,source=planned
    edits={'app.py':dict(kind='modified',content="def greet(name):\n    return 'Hello ' + name.strip()\n",summary='Trim'), 'old.py':None,'new.py':None}
    primary=Spy(json.dumps(dict(explanation='Fixture change',files=edits)))
    provider=GatewayDevelopmentProvider(config(),gateway(primary))
    token=approval_identity(state,storage)
    artifact=Developer(provider).develop(state,storage,token)
    assert artifact.approval_id==token and (source/'app.py').read_text().endswith('+ name\n')
    assert primary.requests[0].purpose=='development'


def test_reviewer_rejection_is_not_provider_failure(developed):
    state,storage,_=developed;fallback=Spy()
    primary=Spy(json.dumps(dict(approved=False,summary='Fixture rejection',findings=[dict(severity='medium',file='app.py',line=2,
        evidence="return 'Hello ' + name.strip()",description='Fixture semantic concern',recommended_fix='Inspect requirements')])) )
    result=Reviewer(GatewayReviewProvider(config(),gateway(primary,fallback))).review(state,storage)
    assert not result.approved and not fallback.requests and primary.requests[0].purpose=='review'


def test_semantic_evidence_gateway_can_only_support():
    c,s=criterion(),evidence_source()
    primary=Spy(json.dumps(dict(associations=[dict(criterion_id=str(c.id),source_id=s.id)])))
    context=EvidenceContext(task=dict(repository_path='.',user_request='Fixture'),criteria=[c],sources=[s])
    provider=GatewayEvidenceProvider(config(),gateway(primary))
    result=map_evidence([c],[s],provider.generate(context))
    assert result[0]['status']=='supported' and primary.requests[0].purpose=='acceptance_evidence'


@pytest.mark.parametrize('values,provider,compat',[
    ({'ollama_model':'legacy'},'ollama',True),({},'nvidia',False),({'nvidia_api_key':KEY},'nvidia',False),
    ({'model_primary_provider':'nvidia','ollama_model':'legacy'},'nvidia',False),
    ({'model_primary_provider':'ollama','ollama_model':'legacy','nvidia_api_key':KEY},'ollama',False)])
def test_configuration_precedence(values,provider,compat):
    route=resolve_route(Settings(_env_file=None,**values))
    assert route.provider==provider and route.compatibility_mode==compat


def test_legacy_env_file_and_explicit_new_env(tmp_path):
    env=tmp_path/'old.env';env.write_text('ASE_OLLAMA_MODEL=fixture-local\n')
    assert resolve_route(Settings(_env_file=env)).compatibility_mode
    env.write_text('ASE_OLLAMA_MODEL=fixture-local\nASE_MODEL_PRIMARY_PROVIDER=nvidia\n')
    assert resolve_route(Settings(_env_file=env)).provider=='nvidia'


@pytest.mark.parametrize('url',['http://integrate.api.nvidia.com/v1','https://evil.invalid/v1','https://user:secret@integrate.api.nvidia.com/v1',
    'https://integrate.api.nvidia.com/v1?key=secret','https://integrate.api.nvidia.com:444/v1'])
def test_nvidia_endpoint_allowlist(url):
    with pytest.raises(ValidationError):Settings(_env_file=None,nvidia_base_url=url)


@pytest.mark.parametrize('model',['vendor/model:version','vendor/model with spaces','モデル/名称'])
def test_model_ids_are_not_restricted_to_ollama_tags(model):
    assert Settings(_env_file=None,model_primary_model=model).model_primary_model==model


@pytest.mark.parametrize('model',[' ','x\ny','x\x00y','a'*201])
def test_invalid_model_ids_rejected(model):
    with pytest.raises(ValidationError):Settings(_env_file=None,model_primary_model=model)


@pytest.mark.parametrize('values',[{}, {'model_primary_provider':'nvidia'}, {'nvidia_api_key':KEY}])
def test_status_safe_and_startup_without_provider(values):
    settings=Settings(_env_file=None,**values);store=TaskStore('sqlite://')
    with TestClient(create_platform_app(settings,store)) as client:
        assert client.get('/health').status_code==200
        response=client.get('/system/models')
        assert response.status_code==200 and KEY not in response.text and 'Authorization' not in response.text
        assert response.json()['primary']['available'] is None
        assert response.json()['primary']['configured']==bool(values.get('nvidia_api_key'))
    store.close()


def test_nvidia_missing_key_can_use_explicit_local_fallback(ollama_server):
    url,behavior,_=ollama_server;behavior['body']={'done':True,'message':{'content':'{}'}}
    settings=config(nvidia_api_key=None,ollama_base_url=url)
    observations=[];result=ModelGateway(settings).generate(request(),observations.append)
    assert result.provider=='ollama' and observations[-1].fallback_reason=='not_configured'


def test_product_invocations_persist_without_prompts_or_keys(product):
    from autonomous_engineering.application.product_planning import run_product_plan
    _,store,planning,project=product
    job=planning.enqueue(project['id'],'Fixture goal')
    primary,fallback=Spy(ProviderRateLimited('nvidia','Rate limited')),Spy(json.dumps(draft_data()))
    provider=GatewayProductPlanProvider(config(),gateway(primary,fallback))
    assert run_product_plan(config(),planning,'fixture-owner',provider)
    record=planning.get(str(job.goal.id))
    assert record.status=='ready' and len(record.model_invocations)==2 and record.model_invocations[-1].fallback_used
    trace=store.trace(str(job.goal.id));assert len(trace)==2
    assert KEY not in json.dumps(trace) and 'messages' not in json.dumps(trace) and 'Fixture goal' not in json.dumps(trace)


@pytest.mark.parametrize('name',['ASE_NVIDIA_API_KEY','NVIDIA_API_KEY','ASE_MODEL_PRIMARY_PROVIDER'])
def test_preview_excludes_model_credentials(name):
    with pytest.raises(ValidationError):PreviewProfileInput(environment={name:KEY})


def test_worker_fallback_metadata_is_persisted_in_snapshot_and_trace(planned):
    from autonomous_engineering.application.worker import Worker
    from test_durable_platform import queue_development
    from test_test_execution import suite
    from pathlib import Path
    state,storage,_=planned
    suite(Path(state.workspace_path), "        from app import greet\n        self.assertEqual(greet(' Ada '), 'Hello Ada')\n")
    edits={'app.py':dict(kind='modified',content="def greet(name):\n    return 'Hello ' + name.strip()\n",summary='Trim'),'new.py':None,'old.py':None}
    settings=config(workspace_root=storage,test_backend='local')
    fallback=Spy(json.dumps(dict(explanation='Trim names',files=edits)))
    dev=GatewayDevelopmentProvider(settings,gateway(Spy(ProviderRateLimited('nvidia','Rate limited')),fallback))
    review=GatewayReviewProvider(settings,gateway(Spy(json.dumps(dict(approved=True,summary='Fixture approval',findings=[])))))
    store=TaskStore('sqlite://');task_id=queue_development(store,state,storage)
    assert Worker(settings,store,development_provider=dev,review_provider=review).run_once()
    saved=store.get(task_id)
    assert saved['phase']=='succeeded'
    record=next(e for e in saved['snapshot']['executions'] if e['agent']=='developer')
    assert record['model']=='fixture-local' and record['model_invocations'][1]['fallback_reason']=='rate_limited'
    events=[e for e in store.trace(task_id) if e['kind']=='model_invocation']
    assert len(events)==3 and events[1]['data']['fallback_used']
    with TestClient(create_platform_app(settings,store)) as client:
        response=client.get('/tasks/'+task_id+'/trace')
        assert response.status_code==200 and KEY not in response.text and 'Authorization' not in response.text
    store.close()


def test_invalid_developer_scope_does_not_use_fallback(planned):
    state,storage,_=planned;fallback=Spy()
    content=json.dumps(dict(explanation='Fixture',files={'outside.py':dict(kind='created',content='value=1',summary='Fixture')}))
    primary=Spy(content);provider=GatewayDevelopmentProvider(config(),gateway(primary,fallback))
    with pytest.raises(PlanningError):Developer(provider).develop(state,storage,approval_identity(state,storage))
    assert len(primary.requests)==1 and not fallback.requests


def test_status_only_checks_local_catalog_and_caches(monkeypatch):
    calls=[]
    def check(self,model):calls.append(model);return True
    monkeypatch.setattr(OllamaProvider,'check',check)
    settings=Settings(_env_file=None,ollama_model='legacy-local')
    store=TaskStore('sqlite://')
    with TestClient(create_platform_app(settings,store)) as client:
        for _ in range(2):
            data=client.get('/system/models').json()
            assert data['primary']['available'] is True and data['primary']['status']=='available'
            assert data['compatibility_mode'] and not data['fallback']['enabled']
    assert calls==['legacy-local']
    store.close()


def test_secret_header_values_and_opaque_ids_do_not_leak():
    transport=Transport((200,completion(),KEY))
    response=NvidiaNimProvider(config(),transport).generate(request())
    assert response.request_id is None
    with pytest.raises(ProviderAuthenticationError) as error:
        NvidiaNimProvider(config(nvidia_api_key=KEY+'\r\n')).generate(request())
    assert KEY not in str(error.value)


def test_no_provider_work_fails_clearly_without_stopping_platform(product):
    from autonomous_engineering.application.product_planning import run_product_plan
    settings,store,planning,project=product
    job=planning.enqueue(project['id'],'Fixture')
    assert run_product_plan(settings,planning,'fixture-owner')
    assert 'No model provider configured' in planning.get(str(job.goal.id)).error
    with TestClient(create_platform_app(settings,store)) as client:assert client.get('/health').status_code==200
