"""Read-only, secret-free configuration and lightweight local service status."""
import threading
import time
from fastapi import APIRouter
from autonomous_engineering.domain.models import ProviderError
from autonomous_engineering.infrastructure.model_gateway import resolve_route
from autonomous_engineering.infrastructure.model_providers import OllamaProvider


def model_router(settings):
    router = APIRouter(tags=['Models'])
    route = resolve_route(settings)
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
        return {'primary':status(route.provider,route.model),
                'fallback':{'enabled':route.fallback_enabled, **status('ollama',route.fallback_model)},
                'nvidia':status('nvidia', settings.model_primary_model if route.provider == 'nvidia' else 'moonshotai/kimi-k3'),
                'compatibility_mode':route.compatibility_mode, 'configuration_source':'environment',
                'fallback_policy':'Provider availability failures only; authentication and validation failures never fall back.',
                'nvidia_availability_notice':'Configured means a key is detected. Hosted availability is confirmed by model invocations; this page does not run paid generation.'}
    return router
