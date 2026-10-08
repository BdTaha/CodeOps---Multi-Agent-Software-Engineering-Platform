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


def resolve_route(settings):
    explicit = settings.model_primary_provider is not None or settings.model_primary_model is not None
    key = settings.nvidia_api_key is not None and bool(settings.nvidia_api_key.get_secret_value().strip())
    provider = settings.model_primary_provider or ('nvidia' if explicit or key or not settings.ollama_model else 'ollama')
    model = settings.model_primary_model or (KIMI_MODEL if provider == 'nvidia' else settings.ollama_model)
    return ModelRoute(provider, model, settings.model_fallback_enabled and provider != 'ollama',
                      settings.model_fallback_model or settings.ollama_model, not explicit and not key and bool(settings.ollama_model))


def model_configured(settings):
    route = resolve_route(settings)
    return bool((route.provider == 'ollama' and route.model) or
                (route.provider == 'nvidia' and settings.nvidia_api_key and settings.nvidia_api_key.get_secret_value().strip()) or
                (route.fallback_enabled and route.fallback_model))


class ModelGateway:
    def __init__(self, settings, providers=None):
        self.route = resolve_route(settings)
        self.providers = providers if providers is not None else {'nvidia':NvidiaNimProvider(settings), 'ollama':OllamaProvider(settings)}

    def generate(self, request, observe=None):
        primary_error = None
        routes = [(self.route.provider, self.route.model, False)]
        if self.route.fallback_enabled and self.route.fallback_model:
            routes.append(('ollama', self.route.fallback_model, True))
        for provider, model, fallback in routes:
            started = monotonic()
            response = None
            error = None
            try:
                if not model: raise ProviderNotConfigured(provider, 'No model provider configured.')
                response = self.providers[provider].generate(request.model_copy(update={'model':model}, deep=True))
            except ProviderError as exc:
                error = exc
            invocation = ModelInvocation(purpose=request.purpose, provider=provider, model=model or 'not configured',
                outcome=error.reason if error else 'succeeded', fallback_used=fallback,
                fallback_reason=primary_error.reason if primary_error else None, latency_ms=(monotonic()-started)*1000,
                **({k:getattr(response,k) for k in ('request_id','input_tokens','output_tokens','total_tokens')} if response else {}))
            if observe: observe(invocation)
            if error is None: return response
            if fallback: raise CombinedProviderError(primary_error, error) from None
            if not error.fallback_eligible or len(routes) == 1: raise error from None
            primary_error = error
        raise ProviderNotConfigured(self.route.provider, 'No model provider configured.')
