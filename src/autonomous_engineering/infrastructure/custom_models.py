"""Configurable protocols with bounded transport and vetted, pinned destinations."""
import ipaddress
import json
import socket
import ssl
import time
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlsplit, quote
from urllib.request import HTTPHandler, HTTPSHandler, ProxyHandler, build_opener
from types import SimpleNamespace

from autonomous_engineering.domain.models import ModelResponse, ProviderBadRequest, ProviderResponseError, ProviderUnavailable
from autonomous_engineering.infrastructure.model_providers import HttpTransport, NoRedirect, tokens, NvidiaNimProvider, OllamaProvider


def validate_endpoint(value):
    value = value.strip().rstrip('/')
    try:
        url = urlsplit(value)
        host = url.hostname
        port = url.port
        if not host or url.username or url.password or url.query or url.fragment or any(ord(c) <= 32 or ord(c) >= 127 for c in value): raise ValueError()
        if port is not None and not 1 <= port <= 65535: raise ValueError()
        try: address = ipaddress.ip_address(host)
        except ValueError: address = None
        local = host == 'localhost' or (address is not None and address.is_loopback)
        if url.scheme not in ('http', 'https') or (url.scheme == 'http' and not local): raise ValueError()
        if address is not None and not (address.is_global or address.is_loopback): raise ValueError()
        if '%' in host or '\\' in value: raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('Use a public HTTPS API URL, or a loopback URL for a local service, without credentials or query parameters.') from None
    return value


def vetted_addresses(host, port):
    try: addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError: raise ProviderUnavailable('connection', 'Model endpoint could not be resolved.') from None
    local = host == 'localhost'
    try: local = local or ipaddress.ip_address(host).is_loopback
    except ValueError: pass
    if not addresses or any(not (ipaddress.ip_address(item[4][0]).is_loopback if local else ipaddress.ip_address(item[4][0]).is_global) for item in addresses):
        raise ProviderBadRequest('connection', 'Model endpoints cannot access private networks or metadata services.')
    return addresses


def pinned_socket(host, port, timeout, source_address):
    # Connect to the exact vetted IP. TLS still verifies the original hostname.
    addresses = vetted_addresses(host, port)
    for family, kind, proto, _, address in addresses:
        connection = socket.socket(family, kind, proto)
        try:
            connection.settimeout(timeout)
            if source_address: connection.bind(source_address)
            connection.connect(address)
            return connection
        except OSError:
            connection.close()
    raise OSError('Endpoint unavailable')


class PinnedHTTP(HTTPConnection):
    def connect(self):
        self.sock = pinned_socket(self.host, self.port, self.timeout, self.source_address)


class PinnedHTTPS(HTTPSConnection):
    def connect(self):
        sock = pinned_socket(self.host, self.port, self.timeout, self.source_address)
        try: self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class SafeHTTPHandler(HTTPHandler):
    def http_open(self, request): return self.do_open(PinnedHTTP, request)


class SafeHTTPSHandler(HTTPSHandler):
    def https_open(self, request): return self.do_open(PinnedHTTPS, request, context=ssl.create_default_context())


def safe_opener():
    return build_opener(ProxyHandler({}), NoRedirect(), SafeHTTPHandler(), SafeHTTPSHandler())


class ConfiguredProvider:
    def __init__(self, profile, transport=None):
        self.profile = profile
        self.protocol = profile['protocol']
        self.url = validate_endpoint(profile['base_url'])
        self.key = profile.get('key')
        self.transport = transport or HttpTransport(self.protocol, safe_opener)

    def headers(self):
        if not self.key: return {}
        if self.protocol == 'anthropic': return {'x-api-key': self.key, 'anthropic-version': '2023-06-01'}
        if self.protocol == 'gemini': return {'x-goog-api-key': self.key}
        return {'Authorization': 'Bearer '+self.key}

    def reasoning_mode(self, request):
        if self.protocol != 'nvidia': return None
        from autonomous_engineering.infrastructure.nvidia_reasoning import reasoning_control
        return reasoning_control(request.model, self.profile.get('reasoning_policy', 'provider_default'),
            structured=request.structured_schema is not None)['effective_reasoning']

    def catalog(self):
        path = '/api/tags' if self.protocol == 'ollama' else '/models'
        headers = self.headers()
        if self.protocol == 'anthropic': headers['anthropic-version'] = '2023-06-01'
        _, payload, _ = self.transport.send(self.url+path, None, 10, headers)
        items = payload.get('models' if self.protocol in ('ollama', 'gemini') else 'data')
        if not isinstance(items, list): raise ProviderResponseError(self.protocol, 'Provider returned an invalid model catalog. You can enter a model ID manually.')
        result = []
        for item in items[:1000]:
            if not isinstance(item, dict): continue
            if self.protocol == 'gemini' and 'generateContent' not in item.get('supportedGenerationMethods', []): continue
            model = item.get('name' if self.protocol in ('ollama', 'gemini') else 'id')
            if self.protocol == 'gemini' and isinstance(model, str): model = model.removeprefix('models/')
            if isinstance(model, str) and 0 < len(model) <= 200 and not any(ord(c) < 32 for c in model) and not (self.key and self.key in model): result.append(model)
        return sorted(set(result))

    def generate(self, request):
        protocol = self.protocol
        if protocol in ('nvidia', 'ollama'):
            from pydantic import SecretStr
            if protocol == 'ollama':
                provider = OllamaProvider(SimpleNamespace(ollama_base_url=self.url), safe_opener)
                provider.transport = self.transport
            else: provider = NvidiaNimProvider(SimpleNamespace(nvidia_base_url=self.url, nvidia_api_key=SecretStr(self.key) if self.key else None,
                nvidia_structured_mode=self.profile['structured_mode'],
                nvidia_reasoning_policy=self.profile.get('reasoning_policy', 'provider_default')), self.transport)
            return provider.generate(request)
        started = time.monotonic()
        messages = [message.model_dump() for message in request.messages]
        if request.structured_schema and self.profile['structured_mode'] == 'prompt':
            messages.append({'role':'user', 'content':'Return only a JSON object matching this schema: '+json.dumps(request.structured_schema)})
        if protocol == 'openai':
            body = {'model':request.model, 'messages':messages, 'stream':False,
                self.profile['token_parameter']:request.max_output_tokens}
            if self.profile['send_temperature']: body['temperature'] = request.temperature
            if request.structured_schema and self.profile['structured_mode'] != 'prompt':
                body['response_format'] = {'type':self.profile['structured_mode']}
                if self.profile['structured_mode'] == 'json_schema': body['response_format']['json_schema'] = {'name':'codeops_result', 'schema':request.structured_schema}
            path = '/chat/completions'
        elif protocol == 'anthropic':
            body = {'model':request.model, 'system':'\n\n'.join(m['content'] for m in messages if m['role'] == 'system'),
                'messages':[m for m in messages if m['role'] != 'system'], 'max_tokens':request.max_output_tokens}
            if self.profile['send_temperature']: body['temperature'] = request.temperature
            path = '/messages'
        else:
            body = {'systemInstruction':{'parts':[{'text':m['content']} for m in messages if m['role'] == 'system']},
                'contents':[{'role':'model' if m['role'] == 'assistant' else 'user', 'parts':[{'text':m['content']}]} for m in messages if m['role'] != 'system'],
                'generationConfig':{'maxOutputTokens':request.max_output_tokens}}
            if self.profile['send_temperature']: body['generationConfig']['temperature'] = request.temperature
            path = '/models/'+quote(request.model.removeprefix('models/'), safe='')+':generateContent'
        _, payload, request_id = self.transport.send(self.url+path, body, request.timeout_seconds, self.headers())
        try:
            if protocol == 'openai':
                choice = payload['choices'][0]
                if choice['finish_reason'] != 'stop': raise ValueError()
                content = choice['message']['content']
                usage = tokens(payload.get('usage') or {}, [('prompt_tokens','input_tokens'), ('completion_tokens','output_tokens'), ('total_tokens','total_tokens')])
            elif protocol == 'anthropic':
                if payload['stop_reason'] not in ('end_turn', 'stop_sequence'): raise ValueError()
                content = ''.join(part['text'] for part in payload['content'] if part.get('type') == 'text')
                usage = tokens(payload.get('usage') or {}, [('input_tokens','input_tokens'), ('output_tokens','output_tokens')])
            else:
                choice = payload['candidates'][0]
                if choice['finishReason'] != 'STOP': raise ValueError()
                content = ''.join(part['text'] for part in choice['content']['parts'] if 'text' in part and not part.get('thought'))
                usage = tokens(payload.get('usageMetadata') or {}, [('promptTokenCount','input_tokens'), ('candidatesTokenCount','output_tokens'), ('totalTokenCount','total_tokens')])
            if not isinstance(content, str) or not content.strip(): raise ValueError()
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            raise ProviderResponseError(protocol, 'Provider did not return a complete text result.') from None
        if request_id and self.key and self.key in request_id: request_id = None
        return ModelResponse(content=content, provider=protocol, model=request.model, request_id=request_id,
            latency_ms=(time.monotonic()-started)*1000, **usage)
