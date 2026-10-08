"""Secret-free status and local workspace provider configuration."""
import json
import threading
import time
from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from autonomous_engineering.infrastructure.model_settings import ConnectionInput, RouteInput, SettingsConflict
from autonomous_engineering.infrastructure.custom_models import ConfiguredProvider
from autonomous_engineering.domain.models import ProviderError
from autonomous_engineering.infrastructure.model_gateway import resolve_route
from autonomous_engineering.infrastructure.model_providers import OllamaProvider


def model_router(settings):
    router = APIRouter(tags=['Models'])
    store = settings._model_settings_store
    cache = {}
    lock = threading.Lock()
    def status(provider, model):
        key_present = settings.nvidia_api_key is not None and bool(settings.nvidia_api_key.get_secret_value().strip())
        configured = bool(model and (key_present if provider == 'nvidia' else True))
        result = {'provider':provider, 'display_name':'NVIDIA NIM' if provider == 'nvidia' else 'Ollama',
                  'model':model, 'configured':configured, 'available':None, 'status':'not_configured' if not configured else 'not_checked',
                  'model_display_name':'Kimi K3' if model == 'moonshotai/kimi-k3' else model}
        if provider == 'ollama' and configured:
            with lock:
                if cache.get('expires',0) <= time.monotonic():
                    try:
                        available = OllamaProvider(settings).check(model)
                        outcome = 'available' if available else 'model_not_found'
                    except ProviderError as exc:
                        available, outcome = False, exc.reason
                    cache.update(expires=time.monotonic()+15, available=available, status=outcome)
                result.update(available=cache['available'], status=cache['status'])
        return result

    @router.get('/system/models')
    def models():
        route = resolve_route(settings)
        if route.primary_connection:
            def saved_status(connection_id, model):
                profile = store.profile(connection_id) if connection_id else None
                return {'provider':profile['protocol'] if profile else None, 'display_name':profile['name'] if profile else 'No fallback',
                    'model':model, 'model_display_name':model, 'configured':bool(profile and model), 'available':None, 'status':'not_checked' if profile else 'not_configured'}
            return {'primary':saved_status(route.primary_connection, route.model),
                'fallback':{'enabled':route.fallback_enabled, **saved_status(route.fallback_connection, route.fallback_model)},
                'compatibility_mode':False, 'configuration_source':'settings',
                'fallback_policy':'Provider availability failures only; authentication and validation failures never fall back.'}
        return {'primary':status(route.provider,route.model),
                'fallback':{'enabled':route.fallback_enabled, **status('ollama',route.fallback_model)},
                'nvidia':status('nvidia', settings.model_primary_model if route.provider == 'nvidia' else 'moonshotai/kimi-k3'),
                'compatibility_mode':route.compatibility_mode, 'configuration_source':'environment',
                'fallback_policy':'Provider availability failures only; authentication and validation failures never fall back.',
                'nvidia_availability_notice':'Configured means a key is detected. Hosted availability is confirmed by model invocations; this page does not run paid generation.'}

    def require_store():
        if store is None: raise HTTPException(503, 'Model settings storage is unavailable.')
        return store

    def origin(request):
        if request.headers.get('origin') not in {None, str(request.base_url).rstrip('/')} or request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, 'Requests must originate from this local workspace.')
        require_store()
        if settings.model_settings_locked: raise HTTPException(403, 'Model settings are locked by the administrator.')

    async def body(request, schema):
        origin(request)
        if request.headers.get('content-type', '').split(';')[0] != 'application/json': raise HTTPException(415, 'Use application/json.')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16384: raise HTTPException(413, 'Settings request is too large.')
        def unique(items):
            result = {}
            for key, value in items:
                if key in result: raise ValueError()
                result[key] = value
            return result
        try: return schema.model_validate(json.loads(raw, object_pairs_hook=unique))
        except ValidationError as exc:
            # FastAPI's default validation includes submitted inputs (including keys).
            raise HTTPException(422, [{'field':'.'.join(str(part) for part in error['loc']), 'message':error['msg']}
                for error in exc.errors(include_input=False, include_context=False, include_url=False)]) from None
        except (ValueError, RecursionError): raise HTTPException(422, 'Invalid JSON settings request.') from None

    def call(action):
        try: return action()
        except SettingsConflict as exc: raise HTTPException(409, str(exc)) from None
        except ValueError as exc: raise HTTPException(422, str(exc)) from None

    @router.get('/system/models/settings')
    def configuration(): return require_store().snapshot()

    @router.post('/system/models/connections', status_code=201)
    async def add(request: Request):
        data = await body(request, ConnectionInput)
        return await run_in_threadpool(call, lambda:store.save(data))

    @router.put('/system/models/connections/{connection_id}')
    async def edit(connection_id: str, request: Request):
        data = await body(request, ConnectionInput)
        return await run_in_threadpool(call, lambda:store.save(data, connection_id))

    @router.delete('/system/models/connections/{connection_id}')
    def remove(connection_id: str, request: Request, revision: int):
        origin(request)
        call(lambda:store.remove(connection_id, revision))
        return {'removed':True}

    @router.post('/system/models/connections/{connection_id}/catalog')
    def catalog(connection_id: str, request: Request):
        origin(request)
        profile = call(lambda:store.profile(connection_id, secrets=True))
        try: return {'models':ConfiguredProvider(profile).catalog(), 'message':'Catalog connection verified. Generation compatibility is checked when a task runs.'}
        except ProviderError as exc: raise HTTPException(422, {'code':exc.reason, 'message':str(exc)}) from None

    @router.put('/system/models/route')
    async def save_route(request: Request):
        data = await body(request, RouteInput)
        return await run_in_threadpool(call, lambda:store.set_route(data))

    @router.delete('/system/models/route')
    def reset_route(request: Request, revision: int):
        origin(request)
        return call(lambda:store.set_route(revision=revision))
    return router
