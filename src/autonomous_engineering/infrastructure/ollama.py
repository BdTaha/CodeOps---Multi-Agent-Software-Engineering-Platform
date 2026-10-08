"""Legacy local-provider imports; routing now lives in ModelGateway."""
from autonomous_engineering.infrastructure.model_providers import NoRedirect
from autonomous_engineering.infrastructure.structured_model import StructuredModelProvider
from autonomous_engineering.infrastructure.model_planner import GatewayPlanProvider, configured_provider
OllamaStructuredProvider = StructuredModelProvider
OllamaPlanProvider = GatewayPlanProvider
