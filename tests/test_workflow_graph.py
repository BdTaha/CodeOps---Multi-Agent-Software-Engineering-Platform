import asyncio
import json
import os
import subprocess
import sys

import pytest
from langgraph.errors import GraphRecursionError, InvalidUpdateError
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from autonomous_engineering.domain.execution import AgentName, ExecutionStatus
from autonomous_engineering.domain.results import (
    ReportSummary,
    ReviewResults,
    TestExecution,
    TestResults,
)
from autonomous_engineering.domain.tasks import TaskRecord, TaskRequest, TaskStatus
from autonomous_engineering.workflows.graph import build_workflow
from autonomous_engineering.workflows.nodes import GraphState, read_snapshot
from autonomous_engineering.workflows.runner import run_workflow
from autonomous_engineering.workflows.state import WorkflowState, WorkflowUpdate
from autonomous_engineering.tools.repository import InspectionLimits
from pathlib import Path


@pytest.fixture(autouse=True)
def local_tracing_only(monkeypatch, tmp_path) -> None:
    # Tests must not inherit a developer's remote LangSmith tracing configuration.
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING", "false")
    monkeypatch.delenv("ASE_OLLAMA_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def initial(tmp_path) -> WorkflowState:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("def login(): return True\n", encoding="utf-8")
    (source / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi>=0.115"]\n', encoding="utf-8")
    return WorkflowState(task=TaskRecord(request=TaskRequest(
        repository_path=str(source), user_request="Fix login",
    )))


def test_async_graph_reports_missing_capability_with_real_execution_records(initial) -> None:
    result = asyncio.run(run_workflow(initial))
    assert result.task.status == TaskStatus.FAILED
    assert result.task.task_id == initial.task.task_id
    assert result.run_id == initial.run_id
    assert result.current_agent is None
    assert result.task.started_at is not None
    assert result.task.finished_at >= result.task.started_at
    assert [e.operation for e in result.executions] == [
        "initialize_task", "prepare_workspace", "analyze_repository", "plan_implementation", "finalize_failure",
    ]
    assert [e.status for e in result.executions] == [
        ExecutionStatus.SUCCEEDED, ExecutionStatus.SUCCEEDED, ExecutionStatus.SUCCEEDED,
        ExecutionStatus.FAILED, ExecutionStatus.SUCCEEDED,
    ]
    assert [e.attempt for e in result.executions] == [1, 2, 1, 1, 3]
    assert len({e.execution_id for e in result.executions}) == 5
    assert result.executions[2].agent == AgentName.REPOSITORY_ANALYZER
    assert all(e.task_id == result.task.task_id and e.run_id == result.run_id
               for e in result.executions)
    assert all(e.duration_seconds >= 0 and e.ended_at >= e.started_at
               for e in result.executions)
    assert result.errors[0].code == "PLANNER_NOT_CONFIGURED"
    assert not result.errors[0].retryable
    assert result.executions[3].error == result.errors[0]
    assert result.report.outcome == TaskStatus.FAILED
    assert "LLM provider" in result.report.summary
    assert result.analysis.languages == ("Python",)
    assert result.analysis.frameworks == ("FastAPI",)
    assert result.analysis.inspected_file_count == 2
    assert result.plan is result.tests is result.review is None
    assert result.changes == ()
    assert result.development_attempts == 0
    assert initial.task.status == TaskStatus.PENDING
    assert initial.executions == ()


def test_sync_stream_exposes_validated_sequential_snapshots(initial) -> None:
    events = list(build_workflow().stream({"snapshot": initial}, stream_mode="updates"))
    assert [next(iter(event)) for event in events] == [
        "supervisor", "prepare_workspace", "analyze_repository", "plan_implementation", "finalize_failure",
    ]
    for index, event in enumerate(events, start=1):
        snapshot = read_snapshot(next(iter(event.values())))
        assert len(snapshot.executions) == index
        assert snapshot.task.status == (TaskStatus.FAILED if index == 5 else TaskStatus.RUNNING)


def test_json_input_and_output_preserve_contracts(initial) -> None:
    # JSON-only input models the later API/storage boundary, without a database.
    output = build_workflow().invoke({"snapshot": json.loads(initial.model_dump_json())})
    result = WorkflowState.model_validate(output["snapshot"])
    restored = WorkflowState.model_validate_json(result.model_dump_json())
    assert restored == result
    assert restored.task.task_id == initial.task.task_id
    assert restored.executions[3].error.code == "PLANNER_NOT_CONFIGURED"


@pytest.mark.parametrize("status", [TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.SUCCEEDED])
def test_terminal_entry_routes_to_end_without_new_execution(initial, status) -> None:
    if status == TaskStatus.CANCELLED:
        terminal = initial.apply(WorkflowUpdate(status=status))
    elif status == TaskStatus.FAILED:
        terminal = asyncio.run(run_workflow(initial))
    else:
        running = initial.apply(WorkflowUpdate(status=TaskStatus.RUNNING))
        terminal = running.apply(WorkflowUpdate(
            status=TaskStatus.SUCCEEDED,
            tests=TestResults(
                outcome="passed", summary="Fixture evidence",
                executions=(TestExecution(command=("pytest",), exit_code=0,
                                         duration_seconds=0.1, output_summary="Fixture pass"),),
            ),
            review=ReviewResults(approved=True, summary="Fixture approval"),
            report=ReportSummary(outcome=TaskStatus.SUCCEEDED, summary="Fixture report"),
        ))
    result = asyncio.run(run_workflow(terminal))
    assert result == terminal
    assert list(build_workflow().stream({"snapshot": terminal}, stream_mode="updates")) == []


def test_running_entry_is_rejected_without_claiming_resume(initial) -> None:
    running = initial.apply(WorkflowUpdate(status=TaskStatus.RUNNING))
    with pytest.raises(ValueError, match="checkpoint support"):
        asyncio.run(run_workflow(running))


def test_malformed_graph_input_is_validated_before_any_node(initial) -> None:
    malformed = initial.model_dump(mode="json")
    malformed["task"]["status"] = "running"  # Missing started_at.
    with pytest.raises(ValidationError):
        build_workflow().invoke({"snapshot": malformed})


def test_graph_validation_rejects_false_success_before_channel_write(initial) -> None:
    def invalid_node(state: GraphState) -> GraphState:
        current = read_snapshot(state).apply(WorkflowUpdate(status=TaskStatus.RUNNING))
        return {"snapshot": current.apply(WorkflowUpdate(status=TaskStatus.SUCCEEDED))}

    builder = StateGraph(GraphState)
    builder.add_node("invalid", invalid_node)
    builder.add_edge(START, "invalid")
    builder.add_edge("invalid", END)
    with pytest.raises(ValidationError, match="passing test evidence"):
        builder.compile().invoke({"snapshot": initial})
    assert initial.task.status == TaskStatus.PENDING


def test_graph_applies_invalidation_before_replacing_snapshot(initial) -> None:
    running = initial.apply(WorkflowUpdate(status=TaskStatus.RUNNING,
        tests=TestResults(outcome="passed", summary="Fixture pass", executions=(TestExecution(
            command=("pytest",), exit_code=0, duration_seconds=0.1, output_summary="Fixture pass",
        ),)), review=ReviewResults(approved=True, summary="Fixture approval"),
        report=ReportSummary(outcome="succeeded", summary="Fixture report"),
    ))

    def develop(state: GraphState) -> GraphState:
        return {"snapshot": read_snapshot(state).apply(WorkflowUpdate(
            current_agent="developer", development_attempt_increment=1,
        ))}

    builder = StateGraph(GraphState)
    builder.add_node("update", develop)
    builder.add_edge(START, "update")
    builder.add_edge("update", END)
    output = builder.compile().invoke({"snapshot": running})["snapshot"]
    assert output.tests is output.review is output.report is None
    assert output.development_attempts == 1
    assert running.tests is not None


def test_single_channel_rejects_parallel_writers(initial) -> None:
    def unchanged(state: GraphState) -> GraphState:
        return {"snapshot": read_snapshot(state)}

    builder = StateGraph(GraphState)
    builder.add_node("one", unchanged)
    builder.add_node("two", unchanged)
    builder.add_edge(START, "one")
    builder.add_edge(START, "two")
    builder.add_edge("one", END)
    builder.add_edge("two", END)
    with pytest.raises(InvalidUpdateError):
        builder.compile().invoke({"snapshot": initial})


def test_graph_respects_recursion_limit(initial) -> None:
    with pytest.raises(GraphRecursionError):
        build_workflow().invoke({"snapshot": initial}, config={"recursion_limit": 1})


def test_independent_runs_do_not_share_history(initial) -> None:
    second = WorkflowState(task=TaskRecord(request=initial.task.request))

    async def run_both():
        return await asyncio.gather(run_workflow(initial), run_workflow(second))

    one, two = asyncio.run(run_both())
    assert one.run_id != two.run_id
    assert one.task.task_id != two.task.task_id
    assert {e.execution_id for e in one.executions}.isdisjoint(
        {e.execution_id for e in two.executions}
    )


def test_cli_emits_json_and_expected_unsuccessful_exit_code(initial) -> None:
    result = subprocess.run(
        [sys.executable, "-W", "error", "-m", "autonomous_engineering.workflows.cli",
         "--repository", initial.task.request.repository_path, "--request", "Inspect repository"],
        capture_output=True, text=True, timeout=20, env=os.environ.copy(),
    )
    assert result.returncode == 2, result.stderr
    snapshot = WorkflowState.model_validate_json(result.stdout)
    assert snapshot.task.status == TaskStatus.FAILED
    assert snapshot.errors[0].code == "PLANNER_NOT_CONFIGURED"
    assert "Traceback" not in result.stderr
    assert snapshot.analysis.inspected_file_count == 2


def test_missing_repository_is_reported_without_invoking_analyzer() -> None:
    initial = WorkflowState(task=TaskRecord(request=TaskRequest(
        repository_path="missing", user_request="Inspect",
    )))
    result = asyncio.run(run_workflow(initial))
    assert result.errors[0].code == "REPOSITORY_NOT_FOUND"
    assert result.analysis is None
    assert result.workspace_path is None
    assert [e.operation for e in result.executions] == [
        "initialize_task", "prepare_workspace", "finalize_failure",
    ]
    assert result.report.outcome == TaskStatus.FAILED


def test_inspection_limit_is_reported_before_analysis(initial) -> None:
    result = asyncio.run(run_workflow(initial, limits=InspectionLimits(max_files=1)))
    assert result.errors[0].code == "INSPECTION_LIMIT"
    assert result.analysis is None
    assert result.workspace_path is None


def test_workspace_root_is_injectable_and_source_unchanged(initial, tmp_path) -> None:
    source = Path(initial.task.request.repository_path)
    original = (source / "app.py").read_bytes()
    storage = tmp_path / "custom"
    result = asyncio.run(run_workflow(initial, workspace_root=storage))
    assert Path(result.workspace_path).parent == storage
    assert (source / "app.py").read_bytes() == original
    assert result.analysis is not None
    assert result.workspace_notes


def test_pending_task_cannot_supply_an_untrusted_workspace(initial, tmp_path) -> None:
    values = initial.model_dump()
    values["workspace_path"] = str(tmp_path)
    with pytest.raises(ValueError, match="preassigned"):
        asyncio.run(run_workflow(WorkflowState.model_validate(values)))


def test_analyzer_access_failure_routes_to_report_instead_of_planner(initial) -> None:
    graph = build_workflow()
    stream = graph.stream({"snapshot": initial}, stream_mode="updates")
    assert "supervisor" in next(stream)
    prepared = next(stream)["prepare_workspace"]["snapshot"]
    # Simulate a removed snapshot file between preparation and the Analyzer.
    (Path(prepared.workspace_path) / "app.py").unlink()
    # Remove the directory so reader initialization fails, rather than merely
    # changing the inventory. This is our newly created fixture workspace.
    (Path(prepared.workspace_path) / "pyproject.toml").unlink()
    Path(prepared.workspace_path).rmdir()
    remaining = list(stream)
    assert [next(iter(event)) for event in remaining] == ["analyze_repository", "finalize_failure"]
    result = remaining[-1]["finalize_failure"]["snapshot"]
    assert result.errors[-1].code == "REPOSITORY_NOT_FOUND"
    assert result.executions[-2].agent == AgentName.REPOSITORY_ANALYZER
    assert result.executions[-2].status == ExecutionStatus.FAILED
    assert result.analysis is None
