"""Bounded HTTP adapters; never expose provider bodies, headers or exception text."""
import json
import re
import socket
import time
from http.client import HTTPException
from uuid import UUID
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from autonomous_engineering.domain.models import (
    ModelResponse, ProviderUnavailable, ProviderTimeout, ProviderRateLimited,
    ProviderAuthenticationError, ProviderBadRequest, ProviderResponseError, ProviderNotConfigured,
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def safe_request_id(value):
    # Opaque identifiers only; never retain arbitrary response headers.
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value) else None


def tokens(payload, names):
    return {target: payload[source] for source, target in names
            if type(payload.get(source)) is int and payload[source] >= 0}


class HttpTransport:
    def __init__(self, provider, opener=None):
        self.provider = provider
        self.opener = opener

    def send(self, url, body, timeout, headers=None):
        data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
        if data is not None and len(data) > 196608:
            raise ProviderBadRequest(self.provider, 'Model context exceeds the bounded request limit.')
        request = Request(url, data=data, headers={'Content-Type':'application/json', 'Accept':'application/json', **(headers or {})},
                          method='POST' if body is not None else 'GET')
        try:
            opener = self.opener() if self.opener else build_opener(ProxyHandler({}), NoRedirect())
            with opener.open(request, timeout=timeout) as response:
                raw = response.read(262145)
                status = response.status
                request_id = safe_request_id(response.headers.get('NVCF-REQID') or response.headers.get('x-request-id'))
        except HTTPError as exc:
            status = exc.code
            exc.close()
            if status in (401, 403):
                error = ProviderAuthenticationError(self.provider, f'{self.provider} authentication failed. Check ASE_NVIDIA_API_KEY.' if self.provider == 'nvidia' else 'Ollama authentication failed.')
            elif status == 429:
                error = ProviderRateLimited(self.provider, f'{self.provider} is rate limited.')
            elif status in (500, 502, 503, 504):
                error = ProviderUnavailable(self.provider, f'{self.provider} service is temporarily unavailable.')
            else:
                error = ProviderBadRequest(self.provider, 'Ollama model is unavailable. Pull it locally first.' if self.provider == 'ollama' and status == 404 else f'{self.provider} rejected the model request (HTTP {status}).')
                error.status = status
            raise error from None
        except (TimeoutError, socket.timeout):
            raise ProviderTimeout(self.provider, f'{self.provider} model request timed out.') from None
        except URLError as exc:
            error = ProviderTimeout if isinstance(exc.reason, (TimeoutError, socket.timeout)) else ProviderUnavailable
            raise error(self.provider, f'{self.provider} model connection failed.') from None
        except OSError:
            raise ProviderUnavailable(self.provider, f'{self.provider} model connection failed.') from None
        except HTTPException:
            raise ProviderUnavailable(self.provider, f'{self.provider} HTTP connection failed.') from None
        except ValueError:
            raise ProviderBadRequest(self.provider, 'Invalid model HTTP request configuration.') from None
        if len(raw) > 262144:
            raise ProviderResponseError(self.provider, 'Model response exceeds the bounded response limit.')
        try:
            payload = json.loads(raw) if raw else {}
            if not isinstance(payload, dict): raise ValueError()
        except (ValueError, RecursionError):
            raise ProviderResponseError(self.provider, 'Provider returned a malformed response.') from None
        return status, payload, request_id


class OllamaProvider:
    def __init__(self, settings, opener=None):
        self.url = settings.ollama_base_url
        self.transport = HttpTransport('ollama', opener)

    def generate(self, request):
        # Route-selected local models must retain the legacy local-only restriction.
        if any(c.isspace() for c in request.model) or request.model.endswith((':cloud', '-cloud')):
            raise ProviderBadRequest('ollama', 'Use a locally pulled Ollama model tag.')
        options = {'temperature': request.temperature, 'num_predict': request.max_output_tokens}
        if request.context_tokens: options['num_ctx'] = request.context_tokens
        body = {'model':request.model, 'stream':False, 'messages':[m.model_dump() for m in request.messages], 'options':options}
        if request.structured_schema: body['format'] = request.structured_schema
        started = time.monotonic()
        _, payload, rid = self.transport.send(self.url+'/api/chat', body, request.timeout_seconds)
        usage = tokens(payload, [('prompt_eval_count','input_tokens'), ('eval_count','output_tokens')])
        message = payload.get('message', {})
        if payload.get('done') is not True or payload.get('done_reason') == 'length' or not isinstance(message, dict) or not isinstance(message.get('content'), str):
            raise ProviderResponseError('ollama', 'Ollama did not return a complete model result.')
        return ModelResponse(content=message['content'], provider='ollama', model=request.model,
                             latency_ms=(time.monotonic()-started)*1000, request_id=rid, **usage)

    def check(self, model):
        _, payload, _ = self.transport.send(self.url+'/api/tags', None, 3)
        models = payload.get('models')
        if not isinstance(models, list):
            raise ProviderResponseError('ollama', 'Ollama returned an invalid local model catalog.')
        return any(item.get('name') in {model, model+':latest'} for item in models if isinstance(item, dict))


class NvidiaNimProvider:
    def __init__(self, settings, transport=None):
        self.url = settings.nvidia_base_url
        self.key = settings.nvidia_api_key
        self.structured_mode = settings.nvidia_structured_mode
        self.transport = transport or HttpTransport('nvidia')

    def generate(self, request):
        if self.key is None or not self.key.get_secret_value().strip():
            raise ProviderNotConfigured('nvidia', 'NVIDIA NIM is not configured. Set ASE_NVIDIA_API_KEY.')
        if any(ord(c) <= 32 or ord(c) >= 127 for c in self.key.get_secret_value()):
            raise ProviderAuthenticationError('nvidia', 'NVIDIA authentication configuration is invalid. Check ASE_NVIDIA_API_KEY.')
        headers = {'Authorization': 'Bearer '+self.key.get_secret_value()}
        body = {'model':request.model, 'messages':[m.model_dump() for m in request.messages],
                'temperature':request.temperature, 'max_tokens':request.max_output_tokens, 'stream':False}
        if request.model == 'moonshotai/kimi-k3': body['reasoning_effort'] = 'low'
        # Hosted K3 reference does not document response_format. Explicit opt-in
        # supports other compatible catalog models; no silent parameter downgrade.
        if request.structured_schema and self.structured_mode != 'prompt':
            body['response_format'] = {'type':self.structured_mode}
            if self.structured_mode == 'json_schema':
                body['response_format']['json_schema'] = {'name':'codeops_result', 'schema':request.structured_schema}
        started = time.monotonic()
        deadline = started + request.timeout_seconds
        status, payload, rid = self.transport.send(self.url+'/chat/completions', body, request.timeout_seconds, headers)
        while status == 202:
            try: pending_id = str(UUID(rid or payload.get('requestId', '')))
            except (ValueError, TypeError, AttributeError):
                raise ProviderResponseError('nvidia', 'NVIDIA returned a pending result without a valid request ID.') from None
            remaining = deadline-time.monotonic()
            if remaining <= 0: raise ProviderTimeout('nvidia', 'NVIDIA model request timed out while pending.')
            time.sleep(min(0.5, remaining))
            remaining = deadline-time.monotonic()
            if remaining <= 0: raise ProviderTimeout('nvidia', 'NVIDIA model request timed out while pending.')
            status, payload, new_id = self.transport.send(self.url+'/status/'+pending_id, None, remaining, headers)
            rid = new_id or pending_id
        try:
            choice = payload['choices'][0]
            content = choice['message']['content']
            if status != 200 or choice.get('finish_reason') != 'stop' or not isinstance(content, str) or not content.strip(): raise ValueError()
            usage = payload.get('usage') or {}
            if not isinstance(usage, dict): usage = {}
            observed = tokens(usage, [('prompt_tokens','input_tokens'), ('completion_tokens','output_tokens'), ('total_tokens','total_tokens')])
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderResponseError('nvidia', 'NVIDIA did not return a complete model result.') from None
        rid = rid or safe_request_id(payload.get('id'))
        if rid and self.key.get_secret_value() in rid: rid = None
        return ModelResponse(content=content, provider='nvidia', model=request.model, request_id=rid,
                             latency_ms=(time.monotonic()-started)*1000, **observed)
