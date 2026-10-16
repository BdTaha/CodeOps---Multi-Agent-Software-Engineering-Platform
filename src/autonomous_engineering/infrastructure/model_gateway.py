"""One primary, one sequential availability fallback. No semantic retry."""
from dataclasses import dataclass
from time import monotonic
from autonomous_engineering.domain.models import ModelInvocation, ProviderError, ProviderNotConfigured, CombinedProviderError
from autonomous_engineering.infrastructure.model_providers import NvidiaNimProvider, OllamaProvider

KIMI_MODEL = 'moonshotai/kimi-k3'


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str | None
    fallback_enabled: bool
    fallback_model: str | None
    compatibility_mode: bool = False
    fallback_provider: str = 'ollama'
    primary_connection: str | None = None
    fallback_connection: str | None = None
    provider_name: str | None = None
    fallback_name: str | None = None


def resolve_route(settings, use_saved=True):
    store = settings._model_settings_store
    saved = store.runtime(secrets=False) if store and use_saved else None
    if saved:
        route, profiles = saved
        primary = profiles[route['primary_connection']]
        fallback = profiles.get(route.get('fallback_connection'))
        return ModelRoute(primary['protocol'], route['primary_model'], route['fallback_enabled'], route.get('fallback_model'),
            fallback_provider=fallback['protocol'] if fallback else 'ollama', primary_connection=primary['id'],
            fallback_connection=fallback['id'] if fallback else None, provider_name=primary['name'], fallback_name=fallback['name'] if fallback else None)
    explicit = settings.model_primary_provider is not None or settings.model_primary_model is not None
    key = settings.nvidia_api_key is not None and bool(settings.nvidia_api_key.get_secret_value().strip())
    provider = settings.model_primary_provider or ('nvidia' if explicit or key or not settings.ollama_model else 'ollama')
    model = settings.model_primary_model or (KIMI_MODEL if provider == 'nvidia' else settings.ollama_model)
    return ModelRoute(provider, model, settings.model_fallback_enabled and provider != 'ollama',
                      settings.model_fallback_model or settings.ollama_model, not explicit and not key and bool(settings.ollama_model))


def model_configured(settings):
    route = resolve_route(settings)
    if route.primary_connection: return bool(route.model)
    return bool((route.provider == 'ollama' and route.model) or
                (route.provider == 'nvidia' and settings.nvidia_api_key and settings.nvidia_api_key.get_secret_value().strip()) or
                (route.fallback_enabled and route.fallback_model))


class ModelGateway:
    def __init__(self, settings, providers=None):
        saved = settings._model_settings_store.runtime() if settings._model_settings_store else None
        self.route = resolve_route(settings, use_saved=False)
        self.providers = providers if providers is not None else {'nvidia':NvidiaNimProvider(settings), 'ollama':OllamaProvider(settings)}
        if providers is None and saved:
            from autonomous_engineering.infrastructure.custom_models import ConfiguredProvider
            # Read routing and credentials together; each operation keeps its own snapshot.
            saved_route, profiles = saved
            primary = profiles[saved_route['primary_connection']]
            fallback = profiles.get(saved_route.get('fallback_connection'))
            self.route = ModelRoute(primary['protocol'], saved_route['primary_model'], saved_route['fallback_enabled'], saved_route.get('fallback_model'),
                fallback_provider=fallback['protocol'] if fallback else 'ollama', primary_connection=primary['id'],
                fallback_connection=fallback['id'] if fallback else None, provider_name=primary['name'], fallback_name=fallback['name'] if fallback else None)
            self.providers = {cid:ConfiguredProvider(profile) for cid, profile in profiles.items()}

    def generate(self, request, observe=None):
        primary_error = None
        routes = [(self.route.provider, self.route.model, False, self.route.primary_connection or self.route.provider, self.route.provider_name)]
        if self.route.fallback_enabled and self.route.fallback_model:
            routes.append((self.route.fallback_provider, self.route.fallback_model, True, self.route.fallback_connection or self.route.fallback_provider, self.route.fallback_name))
        for provider, model, fallback, connection, name in routes:
            started = monotonic()
            response = None
            error = None
            reasoning = None
            try:
                if not model: raise ProviderNotConfigured(provider, 'No model provider configured.')
                adapter = self.providers[connection]
                selected = request.model_copy(update={'model':model}, deep=True)
                if hasattr(adapter, 'reasoning_mode'): reasoning = adapter.reasoning_mode(selected)
                response = adapter.generate(selected)
            except ProviderError as exc:
                error = exc
            invocation = ModelInvocation(purpose=request.purpose, provider=provider, model=model or 'not configured',
                provider_name=name,
                reasoning=reasoning,
                outcome=error.reason if error else 'succeeded', fallback_used=fallback,
                fallback_reason=primary_error.reason if primary_error else None, latency_ms=(monotonic()-started)*1000,
                **({k:getattr(response,k) for k in ('request_id','input_tokens','output_tokens','total_tokens')} if response else {}))
            if observe: observe(invocation)
            if error is None: return response
            if fallback: raise CombinedProviderError(primary_error, error) from None
            if not error.fallback_eligible or len(routes) == 1: raise error from None
            primary_error = error
        raise ProviderNotConfigured(self.route.provider, 'No model provider configured.')
