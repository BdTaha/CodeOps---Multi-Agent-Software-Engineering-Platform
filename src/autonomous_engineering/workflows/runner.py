"""Async execution boundary that always returns a validated workflow snapshot."""

from autonomous_engineering.workflows.graph import build_workflow
from autonomous_engineering.workflows.state import WorkflowState
from autonomous_engineering.core.config import Settings
from autonomous_engineering.tools.repository import InspectionLimits
from pathlib import Path
from autonomous_engineering.agents.planner import PlanProvider
from autonomous_engineering.infrastructure.model_planner import configured_provider


async def run_workflow(
    state: WorkflowState, *, workspace_root: Path | None = None,
    limits: InspectionLimits | None = None,
    planner_provider: PlanProvider | None = None,
    settings: Settings | None = None,
) -> WorkflowState:
    """Run locally; does not schedule durable work or support checkpoint resume."""
    validated = WorkflowState.model_validate(state)
    config = settings if settings is not None else Settings()
    storage = workspace_root if workspace_root is not None else config.workspace_root
    provider = planner_provider if planner_provider is not None else configured_provider(config)
    result = await build_workflow(workspace_root=storage, limits=limits, planner_provider=provider).ainvoke(
        {"snapshot": validated}, config={"recursion_limit": 8}
    )
    return WorkflowState.model_validate(result["snapshot"])
