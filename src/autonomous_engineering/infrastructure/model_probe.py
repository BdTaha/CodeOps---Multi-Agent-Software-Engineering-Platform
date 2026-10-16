"""Opt-in, single-model generation probe. Never returns provider output or prompts."""
import json
from time import monotonic

from autonomous_engineering.domain.models import ModelInvocation, ModelMessage, ModelRequest, ProviderError
from autonomous_engineering.infrastructure.custom_models import ConfiguredProvider

PROBE_TIMEOUT_SECONDS = 25
PROBE_MAX_TOKENS = 32
PROBE_PROMPT = 'Return only this JSON object: {"status":"ok"}'
PROBE_SCHEMA = {'type':'object', 'properties':{'status':{'type':'string','enum':['ok']}},
                'required':['status'], 'additionalProperties':False}


def test_selected_model(profile, model):
    provider = ConfiguredProvider(profile)
    request = ModelRequest(purpose='compatibility_test', model=model,
        messages=(ModelMessage(role='user', content=PROBE_PROMPT),),
        max_output_tokens=PROBE_MAX_TOKENS, timeout_seconds=PROBE_TIMEOUT_SECONDS,
        structured_schema=PROBE_SCHEMA)
    started, response, reasoning = monotonic(), None, None
    outcome = 'succeeded'
    try:
        reasoning = provider.reasoning_mode(request)
        response = provider.generate(request)
        try:
            if json.loads(response.content) != {'status':'ok'}: outcome = 'invalid_response'
        except (ValueError, RecursionError): outcome = 'invalid_response'
    except ProviderError as exc:
        outcome = exc.reason
    message = {
        'succeeded':'Tiny JSON generation check passed. Large engineering tasks may still fail.',
        'timeout':'Selected model timed out during the 25-second generation check.',
        'bad_request':'Selected model rejected the request or reasoning configuration. Check its supported controls.',
        'authentication_failed':'Selected model authentication failed. Check the saved credential.',
        'rate_limited':'Selected model is rate limited.',
        'unavailable':'Selected model service is unavailable.',
        'not_configured':'Selected model is not configured.',
    }.get(outcome, 'Selected model returned an invalid or incomplete response.')
    invocation = ModelInvocation(purpose='compatibility_test', provider=profile['protocol'], model=model,
        outcome=outcome, reasoning=reasoning, latency_ms=(monotonic()-started)*1000,
        **({key:getattr(response,key) for key in ('input_tokens','output_tokens','total_tokens')} if response else {}))
    return {'compatible':outcome == 'succeeded', 'outcome':outcome, 'message':message,
        'timeout_seconds':PROBE_TIMEOUT_SECONDS, 'max_output_tokens':PROBE_MAX_TOKENS,
        'invocation':invocation.model_dump()}
