"""No live credentials: exact NVIDIA compatibility profiles and bounded probes."""
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, update

from test_model_gateway import config, request, completion, Transport, Spy, gateway
from test_model_settings import system, KEY, route
from autonomous_engineering.domain.models import ProviderBadRequest, ProviderTimeout, ProviderResponseError
from autonomous_engineering.infrastructure.custom_models import ConfiguredProvider
from autonomous_engineering.infrastructure.model_gateway import ModelGateway
from autonomous_engineering.infrastructure.model_providers import NvidiaNimProvider
from autonomous_engineering.infrastructure.model_settings import ConnectionInput, ModelSettingsStore, connections
from autonomous_engineering.infrastructure.nvidia_reasoning import LAGUNA_MODEL, KIMI_MODEL, NEMOTRON_MODEL
from autonomous_engineering.platform import create_platform_app


@pytest.mark.parametrize('policy', ['provider_default', 'disabled', 'enabled'])
@pytest.mark.parametrize('model', [LAGUNA_MODEL, NEMOTRON_MODEL])
def test_exact_thinking_profile_payload_uses_only_documented_control(policy, model):
    transport = Transport((200, completion(), None))
    provider = NvidiaNimProvider(config(nvidia_reasoning_policy=policy), transport)
    req = request().model_copy(update={'model':model})
    provider.generate(req)
    body = transport.calls[0][1]
    assert body['chat_template_kwargs'] == {'enable_thinking':policy == 'enabled'}
    assert 'reasoning_effort' not in body
    assert provider.reasoning_mode(req) == ('enabled' if policy == 'enabled' else 'disabled')


@pytest.mark.parametrize('model', ['generic/model', 'poolside/laguna-xs-2.1-other', 'other/poolside/laguna-xs-2.1',
    NEMOTRON_MODEL+'-other', 'other/'+NEMOTRON_MODEL])
def test_provider_default_does_not_guess_generic_model_capabilities(model):
    transport = Transport((200, completion(), None))
    NvidiaNimProvider(config(), transport).generate(request().model_copy(update={'model':model}))
    assert 'reasoning_effort' not in transport.calls[0][1]
    assert 'chat_template_kwargs' not in transport.calls[0][1]


@pytest.mark.parametrize('model', ['openai/gpt-oss-20b', 'openai/gpt-oss-120b'])
@pytest.mark.parametrize('effort', ['low', 'medium', 'high'])
def test_documented_effort_levels(model, effort):
    transport = Transport((200, completion(), None))
    NvidiaNimProvider(config(nvidia_reasoning_policy=effort), transport).generate(request().model_copy(update={'model':model}))
    assert transport.calls[0][1]['reasoning_effort'] == effort
    assert 'chat_template_kwargs' not in transport.calls[0][1]


@pytest.mark.parametrize('policy,effort', [('provider_default','low'), ('low','low'), ('high','high')])
def test_kimi_retains_legacy_low_and_accepts_documented_overrides(policy, effort):
    transport = Transport((200, completion(), None))
    NvidiaNimProvider(config(nvidia_reasoning_policy=policy), transport).generate(request())
    assert transport.calls[0][1]['reasoning_effort'] == effort


@pytest.mark.parametrize('model,policy', [(LAGUNA_MODEL,'low'), (LAGUNA_MODEL,'medium'), (LAGUNA_MODEL,'high'),
    (NEMOTRON_MODEL,'low'), (NEMOTRON_MODEL,'medium'), (NEMOTRON_MODEL,'high'),
    (KIMI_MODEL,'medium'), (KIMI_MODEL,'disabled'), ('generic/model','disabled'), ('generic/model','low')])
def test_unsupported_overrides_never_reach_transport_or_fallback(model, policy):
    transport = Transport()
    provider = NvidiaNimProvider(config(nvidia_reasoning_policy=policy), transport)
    backup = Spy()
    observed = []
    gw = ModelGateway(config(model_primary_model=model), {'nvidia':provider,'ollama':backup})
    with pytest.raises(ProviderBadRequest, match='reasoning|thinking'):
        gw.generate(request(), observed.append)
    assert not transport.calls and not backup.requests
    assert len(observed) == 1 and observed[0].outcome == 'bad_request'


def nvidia(saved, policy='provider_default'):
    return saved.save(ConnectionInput(name='NVIDIA',protocol='nvidia',
        base_url='https://integrate.api.nvidia.com/v1',api_key=KEY,reasoning_policy=policy))


def test_saved_policy_roundtrip_old_rows_and_encryption(system):
    settings, tasks, saved = system
    profile = nvidia(saved, 'disabled')
    reopened = ModelSettingsStore(settings, tasks.engine)
    assert reopened.profile(profile['id'])['reasoning_policy'] == 'disabled'
    assert reopened.profile(profile['id'],secrets=True)['key'] == KEY
    with tasks.engine.begin() as db:
        row = db.execute(select(connections).where(connections.c.id==profile['id'])).mappings().one()
        assert KEY not in row['profile'] and KEY not in row['encrypted_key']
        old_profile = json.loads(row['profile'])
        del old_profile['reasoning_policy']
        db.execute(update(connections).where(connections.c.id==profile['id']).values(profile=json.dumps(old_profile)))
    legacy = reopened.profile(profile['id'])
    assert legacy['reasoning_policy'] == 'provider_default'
    route(saved, legacy, model=KIMI_MODEL)
    transport = Transport((200, completion(), None))
    runtime_profile = reopened.runtime()[1][profile['id']]
    ConfiguredProvider(runtime_profile, transport).generate(request())
    assert transport.calls[0][1]['reasoning_effort'] == 'low'
    with tasks.engine.connect() as db:
        assert db.execute(select(connections.c.encrypted_key)).scalar_one() == row['encrypted_key']


def test_route_and_connection_edits_reject_unsupported_active_policy(system):
    _, _, saved = system
    profile = nvidia(saved, 'disabled')
    with pytest.raises(ValueError,match='thinking'): route(saved,profile,model=KIMI_MODEL)
    route(saved,profile,model=LAGUNA_MODEL)
    with pytest.raises(ValueError,match='unsupported'):
        saved.save(ConnectionInput(name='NVIDIA',protocol='nvidia',base_url=profile['base_url'],
            revision=profile['revision'],reasoning_policy='high'),profile['id'])
    assert saved.profile(profile['id'])['reasoning_policy'] == 'disabled'


@pytest.mark.parametrize('protocol', ['openai','ollama','anthropic','gemini'])
def test_reasoning_is_not_a_cross_protocol_override(protocol):
    with pytest.raises(ValidationError,match='only for NVIDIA'):
        ConnectionInput(name='Other',protocol=protocol,base_url='https://api.example.com',reasoning_policy='disabled')


def test_laguna_effective_reasoning_is_recorded_without_content():
    transport = Transport((200, completion(), None))
    observed = []
    gw = ModelGateway(config(model_primary_model=LAGUNA_MODEL),
        {'nvidia':NvidiaNimProvider(config(),transport), 'ollama':Spy()})
    gw.generate(request(), observed.append)
    assert observed[0].reasoning == 'disabled'
    serialized = observed[0].model_dump_json()
    assert 'PRIVATE_REASONING' not in serialized and 'Fixture task' not in serialized
    assert 'PRIVATE_TEST_NVIDIA_KEY' not in serialized


@pytest.mark.parametrize('outcome,expected', [('ok','succeeded'), ('invalid','invalid_response'), ('timeout','timeout'), ('rejected','bad_request')])
def test_selected_model_probe_is_bounded_single_call_secret_free(system, monkeypatch, caplog, outcome, expected):
    settings, tasks, saved = system
    profile = nvidia(saved)
    route(saved,profile,model=LAGUNA_MODEL)
    payload = completion('{"status":"ok"}' if outcome=='ok' else 'PRIVATE_GENERATED_OUTPUT')
    value = ProviderTimeout('nvidia','Timed out') if outcome=='timeout' else ProviderBadRequest('nvidia','Rejected') if outcome=='rejected' else (200,payload,None)
    transport = Transport(value)
    monkeypatch.setattr('autonomous_engineering.infrastructure.custom_models.HttpTransport', lambda *args:transport)
    with TestClient(create_platform_app(settings,tasks)) as client:
        response = client.post(f"/system/models/connections/{profile['id']}/test",json={'model':LAGUNA_MODEL,'revision':profile['revision']})
        assert response.status_code == 200
        data = response.json()
        assert data['outcome'] == expected and data['compatible'] == (outcome=='ok')
        assert data['invocation']['reasoning'] == 'disabled'
        assert not data['invocation']['fallback_used']
        assert data['invocation']['latency_ms'] >= 0
        status = client.get('/system/models').json()
        assert status['primary']['effective_reasoning'] == 'disabled'
        assert status['primary']['reasoning_source'] == 'compatibility_default'
        assert status['request_timeout_seconds'] == settings.planner_timeout_seconds
    assert len(transport.calls) == 1
    _, body, timeout, _ = transport.calls[0]
    assert timeout == 25 and body['max_tokens'] == 32
    assert sum(len(message['content']) for message in body['messages']) < 120
    assert len(body['messages']) == 1 and body['chat_template_kwargs'] == {'enable_thinking':False}
    for forbidden in [KEY, 'PRIVATE_REASONING', 'PRIVATE_GENERATED_OUTPUT', body['messages'][0]['content']]:
        assert forbidden not in response.text and forbidden not in caplog.text
    assert KEY not in json.dumps(saved.snapshot())


def test_probe_rejects_cross_origin_and_stale_revision_without_generation(system, monkeypatch):
    settings, tasks, saved = system
    profile = nvidia(saved)
    transport = Transport()
    monkeypatch.setattr('autonomous_engineering.infrastructure.custom_models.HttpTransport',lambda *args:transport)
    with TestClient(create_platform_app(settings,tasks)) as client:
        url = f"/system/models/connections/{profile['id']}/test"
        assert client.post(url,json={'model':LAGUNA_MODEL,'revision':1},headers={'Origin':'https://evil.example'}).status_code == 403
        assert client.post(url,json={'model':LAGUNA_MODEL,'revision':2}).status_code == 409
        assert client.post(url,json={'model':LAGUNA_MODEL,'revision':1,'prompt':KEY}).status_code == 422
    assert not transport.calls


def test_timeout_falls_back_once_with_reasoning_recorded_but_invalid_output_does_not():
    observed = []
    transport = Transport(ProviderTimeout('nvidia','Timed out'))
    primary = NvidiaNimProvider(config(),transport)
    backup = Spy()
    gw = ModelGateway(config(model_primary_model=LAGUNA_MODEL),{'nvidia':primary,'ollama':backup})
    gw.generate(request(),observed.append)
    assert len(transport.calls) == len(backup.requests) == 1
    assert observed[0].reasoning == 'disabled' and observed[0].outcome == 'timeout'
    assert observed[1].fallback_used and observed[1].fallback_reason == 'timeout'
    transport = Transport((200,completion('not JSON'),None))
    backup = Spy()
    gw = ModelGateway(config(model_primary_model=LAGUNA_MODEL),{'nvidia':NvidiaNimProvider(config(),transport),'ollama':backup})
    # Agent-specific semantic validation still happens after this single transport call.
    assert gw.generate(request()).content == 'not JSON'
    assert len(transport.calls) == 1 and not backup.requests


@pytest.mark.parametrize('policy', ['provider_default', 'enabled'])
def test_nemotron_probe_uses_exact_profile_and_preserves_bounds(system, monkeypatch, caplog, policy):
    settings, tasks, saved = system
    profile = nvidia(saved, policy)
    route(saved, profile, model=NEMOTRON_MODEL)
    transport = Transport((200, completion('{"status":"ok"}'), None))
    monkeypatch.setattr('autonomous_engineering.infrastructure.custom_models.HttpTransport', lambda *args:transport)
    with TestClient(create_platform_app(settings,tasks)) as client:
        response = client.post(f"/system/models/connections/{profile['id']}/test",
            json={'model':NEMOTRON_MODEL,'revision':profile['revision']})
        assert response.status_code == 200 and response.json()['compatible']
        invocation = response.json()['invocation']
        assert invocation['reasoning'] == ('enabled' if policy == 'enabled' else 'disabled')
        assert not invocation['fallback_used'] and invocation['fallback_reason'] is None
        status = client.get('/system/models').json()['primary']
        assert status['effective_reasoning'] == invocation['reasoning']
        assert status['reasoning_source'] == ('connection' if policy == 'enabled' else 'compatibility_default')
    assert len(transport.calls) == 1
    _, body, timeout, _ = transport.calls[0]
    assert body['model'] == NEMOTRON_MODEL
    assert body['chat_template_kwargs'] == {'enable_thinking':policy == 'enabled'}
    assert 'reasoning_effort' not in body
    assert body['max_tokens'] == 32 and timeout == 25
    assert body['messages'] == [{'role':'user','content':'Return only this JSON object: {"status":"ok"}'}]
    for private in (KEY, 'PRIVATE_REASONING', body['messages'][0]['content']):
        assert private not in response.text and private not in caplog.text


@pytest.mark.parametrize('finish_reason,content', [('length','{"status":"ok"}'), ('stop','')])
def test_nemotron_probe_does_not_accept_reasoning_only_or_truncated_output(system, monkeypatch, finish_reason, content):
    settings, tasks, saved = system
    profile = nvidia(saved)
    payload = completion(content)
    payload['choices'][0]['finish_reason'] = finish_reason
    transport = Transport((200, payload, None))
    monkeypatch.setattr('autonomous_engineering.infrastructure.custom_models.HttpTransport', lambda *args:transport)
    with TestClient(create_platform_app(settings,tasks)) as client:
        response = client.post(f"/system/models/connections/{profile['id']}/test",
            json={'model':NEMOTRON_MODEL,'revision':profile['revision']})
        assert response.status_code == 200 and not response.json()['compatible']
        assert response.json()['outcome'] == 'response_error'
        assert 'PRIVATE_REASONING' not in response.text
    assert len(transport.calls) == 1
