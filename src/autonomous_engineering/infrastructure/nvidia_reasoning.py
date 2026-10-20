"""Exact, documented NVIDIA model controls; never infer support from a name."""
from autonomous_engineering.domain.models import ProviderBadRequest

LAGUNA_MODEL = 'poolside/laguna-xs-2.1'
NEMOTRON_MODEL = 'nvidia/nemotron-3.5-super-vl-120b-a12b'
THINKING_MODELS = {LAGUNA_MODEL, NEMOTRON_MODEL}
KIMI_MODEL = 'moonshotai/kimi-k3'
EFFORT_MODELS = {
    KIMI_MODEL: {'low', 'high'},  # NVIDIA K3 documents low/high/max, not medium.
    'openai/gpt-oss-20b': {'low', 'medium', 'high'},
    'openai/gpt-oss-120b': {'low', 'medium', 'high'},
}
POLICIES = {'provider_default', 'disabled', 'enabled', 'low', 'medium', 'high'}


def reasoning_control(model, policy='provider_default', *, structured=True):
    if policy not in POLICIES:
        raise ProviderBadRequest('nvidia', 'Invalid NVIDIA reasoning policy.')
    effective, source = policy, 'connection' if policy != 'provider_default' else 'provider_default'
    if policy == 'provider_default':
        if model == KIMI_MODEL:
            effective, source = 'low', 'legacy_default'
        elif model in THINKING_MODELS and structured:
            effective, source = 'disabled', 'compatibility_default'
    parameters = {}
    if effective in {'disabled', 'enabled'}:
        if model not in THINKING_MODELS:
            raise ProviderBadRequest('nvidia', 'Disabled/Enabled thinking is supported here only for poolside/laguna-xs-2.1 and nvidia/nemotron-3.5-super-vl-120b-a12b. Use Provider default for other models.')
        parameters = {'chat_template_kwargs': {'enable_thinking': effective == 'enabled'}}
    elif effective != 'provider_default':
        if effective not in EFFORT_MODELS.get(model, set()):
            raise ProviderBadRequest('nvidia', 'This reasoning effort is unsupported by the CodeOps profile for the selected model. Kimi K3 supports Low/High; GPT-OSS 20B/120B supports Low/Medium/High. Laguna and Nemotron 3.5 Super use Disabled/Enabled. Other models require Provider default.')
        parameters = {'reasoning_effort': effective}
    return {'effective_reasoning': effective, 'reasoning_source': source, 'parameters': parameters}
