"""Small model transport contract. No agent prompts or business validation."""
from typing import Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field


class ModelMessage(BaseModel):
    role: Literal['system', 'user', 'assistant']
    content: str


class ModelRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    purpose: Literal['product_planning', 'coding_planning', 'development', 'review', 'acceptance_evidence']
    messages: tuple[ModelMessage, ...] = Field(min_length=1)
    model: str = Field(min_length=1, max_length=200)
    temperature: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    max_output_tokens: int = Field(default=4096, ge=1, le=65536)
    context_tokens: int | None = Field(default=None, ge=1, le=1048576)
    structured_schema: dict | None = None
    timeout_seconds: float = Field(default=180, gt=0, le=600, allow_inf_nan=False)


class ModelInvocation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    purpose: str
    provider: str
    provider_name: str | None = None
    model: str
    outcome: str
    fallback_used: bool = False
    fallback_reason: str | None = None
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    request_id: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ModelResponse(BaseModel):
    content: str
    provider: str
    model: str
    latency_ms: float = Field(default=0, ge=0)
    request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ModelProvider(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse: ...


class ProviderError(Exception):
    reason = 'response_error'
    fallback_eligible = False
    def __init__(self, provider: str, message: str):
        self.provider = provider
        super().__init__(message)


class ProviderUnavailable(ProviderError):
    reason = 'unavailable'
    fallback_eligible = True


class ProviderRateLimited(ProviderError):
    reason = 'rate_limited'
    fallback_eligible = True


class ProviderTimeout(ProviderError):
    reason = 'timeout'
    fallback_eligible = True


class ProviderAuthenticationError(ProviderError):
    reason = 'authentication_failed'


class ProviderBadRequest(ProviderError):
    reason = 'bad_request'


class ProviderResponseError(ProviderError):
    pass


class ProviderNotConfigured(ProviderUnavailable):
    reason = 'not_configured'


class CombinedProviderError(ProviderError):
    reason = 'combined_failure'
    def __init__(self, primary: ProviderError, fallback: ProviderError):
        self.fallback_eligible = primary.fallback_eligible and fallback.fallback_eligible
        super().__init__(primary.provider, f'Primary {primary.provider}: {primary}. Fallback {fallback.provider}: {fallback}.')
