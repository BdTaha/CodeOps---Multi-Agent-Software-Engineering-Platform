"""Agent schema/prompt boundary. Domain validation stays outside HTTP adapters."""
import json
from typing import Generic, TypeVar
from pydantic import ValidationError
from autonomous_engineering.agents.planner import PlanningError
from autonomous_engineering.core.config import Settings
from autonomous_engineering.domain.base import DomainModel
Output = TypeVar('Output', bound=DomainModel)


class StructuredModelProvider(Generic[Output]):
    output_model: type[Output]
    system_prompt: str
    invalid_code = "INVALID_PLAN"
    purpose = "planning"
    def __init__(self, settings: Settings, gateway=None) -> None:
        from autonomous_engineering.infrastructure.model_gateway import ModelGateway
        self.gateway = gateway or ModelGateway(settings)
        self.model = self.gateway.route.model
        self.timeout = settings.planner_timeout_seconds
        self.last_usage = None
        self.invocations = []
        self.trace_observer = None

    def _generate(self, context: DomainModel) -> Output:
        from autonomous_engineering.domain.models import ModelRequest, ModelMessage, ProviderError, ProviderResponseError
        self.last_usage = None
        self.invocations = []
        schema = self.response_schema(context)
        evidence = context.model_dump(mode='json')
        evidence['task'] = {'user_request': evidence['task']['user_request']}
        options = self.generation_options()
        purpose = {'planning':'coding_planning', 'product plan':'product_planning',
                   'acceptance evidence mapping':'acceptance_evidence'}.get(self.purpose, self.purpose)
        request = ModelRequest(purpose=purpose, model=self.model or 'not configured',
            messages=(ModelMessage(role='system',content=self.system_prompt+'\nSchema:\n'+json.dumps(schema)+self.system_facts(context)),
                      ModelMessage(role='user',content=json.dumps(evidence,ensure_ascii=False))),
            temperature=options['temperature'], max_output_tokens=options['num_predict'],
            context_tokens=options.get('num_ctx'), structured_schema=schema, timeout_seconds=self.timeout)
        def observed(invocation):
            self.invocations.append(invocation)
            if self.trace_observer:
                self.trace_observer(invocation)
            self.last_usage = {'model':invocation.model, 'model_invocations':tuple(self.invocations)}
            for field in ('input_tokens','output_tokens'):
                value = getattr(invocation,field)
                if value is not None: self.last_usage[field] = value
        try:
            response = self.gateway.generate(request, observe=observed)
            self.model = response.model
            return self.parse_response(response.content, context)
        except ProviderError as exc:
            if isinstance(exc, ProviderResponseError):
                code = self.invalid_code
            elif exc.provider == 'ollama' and exc.reason == 'bad_request' and getattr(exc,'status',None) == 404:
                code = 'OLLAMA_MODEL_NOT_FOUND'
            elif exc.provider == 'ollama' and exc.reason == 'bad_request':
                code = 'OLLAMA_REQUEST_FAILED'
            elif exc.provider == 'ollama' and exc.reason == 'unavailable':
                code = 'OLLAMA_REQUEST_FAILED' if 'service' in str(exc) else 'OLLAMA_UNAVAILABLE'
            else:
                code = exc.provider.upper()+'_'+exc.reason.upper()
            raise PlanningError(code, str(exc), retryable=exc.fallback_eligible) from None
        except PlanningError:
            raise
        except (ValueError, KeyError, TypeError, RecursionError, ValidationError) as exc:
            detail = ''
            if isinstance(exc, ValidationError):
                issues = exc.errors(include_input=False, include_context=False)[:4]
                fields = ', '.join('.'.join(str(p) for p in item['loc']) or 'result' for item in issues)
                detail = f' Invalid fields: {fields}. Required fields and file contents must match the response schema.'
            raise PlanningError(self.invalid_code, f'Model did not return a complete, valid {self.purpose} result.'+detail) from None

    def response_schema(self, context: DomainModel | None = None) -> dict:
        return self.output_model.model_json_schema()

    def parse_response(self, content: str, context: DomainModel) -> Output:
        return self.output_model.model_validate_json(content)

    def system_facts(self, context: DomainModel) -> str:
        return ''

    def generation_options(self) -> dict:
        return {"temperature": 0, "num_predict": 4096, "num_ctx": 16384}
