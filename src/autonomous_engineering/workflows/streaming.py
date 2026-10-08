"""Real node-start and validated snapshot events for local progress consumers."""

import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Literal

from langgraph.config import get_stream_writer

from autonomous_engineering.core.config import Settings
from autonomous_engineering.domain.base import DomainModel, NonBlank, Summary
from autonomous_engineering.workflows.nodes import GraphState
from autonomous_engineering.workflows.state import WorkflowState
from autonomous_engineering.agents.planner import PlanProvider
from autonomous_engineering.infrastructure.model_planner import configured_provider

logger = logging.getLogger(__name__)


class ProgressEvent(DomainModel):
    kind: Literal["run_started", "node_started", "node_completed", "run_finished", "run_error"]
    node: NonBlank | None = None
    snapshot: WorkflowState | None = None
    message: Summary | None = None


def observed_node(
    name: str, operation: Callable[[GraphState], GraphState],
) -> Callable[[GraphState], GraphState]:
    def execute(state: GraphState) -> GraphState:
        # LangGraph supplies a no-op writer when custom streaming is not requested.
        get_stream_writer()({"kind": "node_started", "node": name})
        return operation(state)
    return execute


async def stream_workflow(
    initial: WorkflowState, *, workspace_root: Path | None = None,
    planner_provider: PlanProvider | None = None, settings: Settings | None = None,
) -> AsyncIterator[ProgressEvent]:
    # Imported locally to keep graph construction independent of this runner.
    from autonomous_engineering.workflows.graph import build_workflow

    snapshot = WorkflowState.model_validate(initial)
    yield ProgressEvent(kind="run_started", snapshot=snapshot)
    config = settings if settings is not None else Settings()
    storage = workspace_root if workspace_root is not None else config.workspace_root
    provider = planner_provider if planner_provider is not None else configured_provider(config)
    try:
        graph = build_workflow(workspace_root=storage, planner_provider=provider)
        async for mode, payload in graph.astream(
            {"snapshot": snapshot}, config={"recursion_limit": 8},
            stream_mode=["custom", "updates"],
        ):
            if mode == "custom":
                yield ProgressEvent.model_validate(payload)
            else:
                for node, update in payload.items():
                    snapshot = WorkflowState.model_validate(update["snapshot"])
                    yield ProgressEvent(kind="node_completed", node=node, snapshot=snapshot)
        yield ProgressEvent(kind="run_finished", snapshot=snapshot)
    except Exception:
        logger.exception("Local workflow stream failed task_id=%s", snapshot.task.task_id)
        yield ProgressEvent(kind="run_error", message="Workflow execution encountered an unexpected error. See the server terminal for details.")
