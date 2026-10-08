"""Synthetic provider responses test contracts; they are never runtime plans."""

import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.error import URLError

import pytest
from pydantic import ValidationError

from autonomous_engineering.agents.planner import Planner, PlanningError
from autonomous_engineering.core.config import Settings
from autonomous_engineering.domain.results import ImplementationPlan, RepositoryAnalysis
from autonomous_engineering.domain.tasks import TaskRecord, TaskRequest
from autonomous_engineering.infrastructure.ollama import OllamaPlanProvider
from autonomous_engineering.tools.repository import RepositoryError, RepositoryReader
from autonomous_engineering.workflows.runner import run_workflow
from autonomous_engineering.workflows.state import WorkflowState
from autonomous_engineering.workflows.streaming import stream_workflow


def fixture_plan():
    return ImplementationPlan(problem_interpretation="Fixture: validate login behavior",
        steps=({"description": "Inspect and correct login validation", "files": ("app.py",)},),
        risks=("Existing callers may rely on current behavior",),
        tests_to_run=("Run targeted login validation tests",))


class CapturingProvider:
    def __init__(self):
        self.context = None

    def generate(self, context):
        self.context = context
        return fixture_plan()


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "app.py").write_text("def login(): return True\n", encoding="utf-8")
    return root


def test_planner_uses_real_readonly_evidence_and_discloses_truncation(source):
    (source / "large.py").write_text("x" * 7000, encoding="utf-8")
    provider = CapturingProvider()
    task = TaskRequest(repository_path=str(source), user_request="Validate login")
    result = Planner(provider).plan(RepositoryReader(source), task, RepositoryAnalysis(
        languages=("Python",), architecture_summary="Fixture observations",
        relevant_files=("app.py", "large.py", "app.py"),))
    assert result.steps == fixture_plan().steps
    assert result.context_files == ("app.py", "large.py")
    assert any("truncated" in item for item in result.limitations)
    assert provider.context.task == task
    assert [e.path for e in provider.context.excerpts] == ["app.py", "large.py"]
    assert provider.context.excerpts[0].content == (source / "app.py").read_bytes().decode("utf-8")
    assert not provider.context.excerpts[0].truncated
    assert len(provider.context.excerpts[1].content) == 6000
    assert provider.context.excerpts[1].truncated
    assert any("truncated" in message for message in provider.context.limitations)
    assert (source / "large.py").read_text() == "x" * 7000


def test_context_budget_and_candidate_omissions_are_explicit(source):
    paths = tuple(f"file{i}.py" for i in range(14))
    for path in paths:
        (source / path).write_text("x" * 6000, encoding="utf-8")
    provider = CapturingProvider()
    Planner(provider).plan(RepositoryReader(source), TaskRequest(repository_path=str(source), user_request="Inspect"),
        RepositoryAnalysis(languages=("Python",), architecture_summary="Fixture", relevant_files=paths))
    assert sum(len(e.content) for e in provider.context.excerpts) == 12000
    assert len(provider.context.excerpts) == 2
    assert any("omitted" in item for item in provider.context.limitations)


def test_missing_candidate_fails_before_provider_call(source):
    provider = CapturingProvider()
    with pytest.raises(RepositoryError):
        Planner(provider).plan(RepositoryReader(source), TaskRequest(repository_path=str(source), user_request="Inspect"),
            RepositoryAnalysis(languages=(), architecture_summary="Fixture", relevant_files=("missing.py",)))
    assert provider.context is None


def test_documentation_cannot_crowd_out_source_candidates(source):
    docs = tuple(f"notes{i}.md" for i in range(9))
    for path in docs:
        (source / path).write_text("x" * 6000, encoding="utf-8")
    provider = CapturingProvider()
    Planner(provider).plan(RepositoryReader(source), TaskRequest(repository_path=str(source), user_request="Fix login"),
        RepositoryAnalysis(languages=("Python",), architecture_summary="Fixture", relevant_files=(*docs, "app.py")))
    assert provider.context.excerpts[0].path == "app.py"
    assert provider.context.excerpts[0].content == (source / "app.py").read_bytes().decode()
    assert any("omitted" in item for item in provider.context.limitations)


def test_invalid_provider_output_never_becomes_a_plan(source):
    class Invalid:
        def generate(self, context):
            return {"problem_interpretation": "Invalid", "steps": [{"description": "Escape", "files": ["../escape.py"]}],
                    "tests_to_run": ["Check"]}
    with pytest.raises(PlanningError, match="invalid implementation plan"):
        Planner(Invalid()).plan(RepositoryReader(source), TaskRequest(repository_path=str(source), user_request="Inspect"),
            RepositoryAnalysis(languages=(), architecture_summary="Fixture"))


def test_graph_generates_draft_then_reports_missing_developer(source, tmp_path):
    provider = CapturingProvider()
    initial = WorkflowState(task=TaskRecord(request=TaskRequest(repository_path=str(source), user_request="Fix login")))
    config = Settings(_env_file=None, environment="test", workspace_root=tmp_path / "snapshots", ollama_model=None)
    result = asyncio.run(run_workflow(initial, settings=config, planner_provider=provider))
    assert result.plan.steps == fixture_plan().steps
    assert result.plan.context_files == ("app.py",)
    assert result.task.status == "failed"
    assert [e.operation for e in result.executions] == ["initialize_task", "prepare_workspace", "analyze_repository",
                                                       "plan_implementation", "check_developer", "finalize_failure"]
    assert result.executions[3].agent == "planner"
    assert result.executions[3].status == "succeeded"
    assert result.errors[-1].code == "PLAN_APPROVAL_REQUIRED"
    assert "approve" in result.report.summary
    assert any("approval has not been granted" in item for item in result.report.limitations)
    assert result.tests is result.review is None and not result.changes
    assert initial.plan is None
    assert (source / "app.py").read_text() == "def login(): return True\n"


def test_provider_failure_routes_directly_to_failure_report(source, tmp_path):
    class Unavailable:
        def generate(self, context):
            raise PlanningError("OLLAMA_UNAVAILABLE", "Fixture unavailable", retryable=True)
    initial = WorkflowState(task=TaskRecord(request=TaskRequest(repository_path=str(source), user_request="Fix login")))
    async def collect():
        return [e async for e in stream_workflow(initial, workspace_root=tmp_path / "snapshots", planner_provider=Unavailable())]
    events = asyncio.run(collect())
    assert events[-1].kind == "run_finished"
    result = events[-1].snapshot
    assert result.plan is None and result.analysis is not None
    assert result.errors[-1].retryable
    assert result.executions[-2].operation == "plan_implementation"
    assert not any(e.node == "check_capability" for e in events)


@pytest.fixture
def ollama_server():
    behavior = {"status": 200, "body": {"done": True, "done_reason": "stop", "message": {"content": fixture_plan().model_dump_json()}}}
    captured = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            captured.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(behavior["status"])
            if behavior["status"] == 302:
                self.send_header("Location", "http://127.0.0.1:1/redirect-target")
            self.end_headers()
            data = behavior["body"]
            self.wfile.write(data if isinstance(data, bytes) else json.dumps(data).encode())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", behavior, captured
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def invoke_local_fixture(source, ollama_server):
    url, _, _ = ollama_server
    config = Settings(_env_file=None, ollama_model="fixture-model", ollama_base_url=url)
    return Planner(OllamaPlanProvider(config)).plan(RepositoryReader(source),
        TaskRequest(repository_path=str(source), user_request="Fix login"),
        RepositoryAnalysis(languages=("Python",), architecture_summary="Fixture", relevant_files=("app.py",)))


def test_ollama_http_schema_prompt_and_revalidation(source, ollama_server):
    result = invoke_local_fixture(source, ollama_server)
    assert result.steps == fixture_plan().steps and result.context_files == ("app.py",)
    _, _, captured = ollama_server
    path, body = captured[0]
    assert path == "/api/chat" and body["stream"] is False
    assert body["format"] == ImplementationPlan.model_json_schema()
    assert body["model"] == "fixture-model"
    assert "untrusted evidence" in body["messages"][0]["content"]
    evidence = json.loads(body["messages"][1]["content"])
    assert "repository_path" not in evidence["task"]
    assert evidence["excerpts"][0]["content"] == (source / "app.py").read_bytes().decode("utf-8")


@pytest.mark.parametrize("payload", [b"not json", {"done": False}, {"done": True, "done_reason": "length"},
    {"done": True, "message": {"content": '{"steps": []}'}},
    {"done": True, "message": {"content": "[]"}}, b"x" * 262145,
    {"done": True, "message": {"content": json.dumps({"problem_interpretation": "Fixture",
        "steps": [{"description": "Too many"}] * 13, "tests_to_run": ["Check"]})}}],
    ids=["malformed", "unfinished", "token-limit", "invalid-plan", "wrong-type", "oversized", "too-many-steps"])
def test_ollama_invalid_or_incomplete_response_is_structured_failure(source, ollama_server, payload):
    ollama_server[1]["body"] = payload
    with pytest.raises(PlanningError) as error:
        invoke_local_fixture(source, ollama_server)
    assert error.value.code == "INVALID_PLAN"


@pytest.mark.parametrize("status,code,retryable", [(404,"OLLAMA_MODEL_NOT_FOUND",False),(500,"OLLAMA_REQUEST_FAILED",True),
                                                  (302,"OLLAMA_REQUEST_FAILED",False)])
def test_ollama_http_errors_do_not_leak_provider_body(source, ollama_server, status, code, retryable):
    ollama_server[1].update(status=status, body=b"PRIVATE_PROVIDER_ERROR")
    with pytest.raises(PlanningError) as error:
        invoke_local_fixture(source, ollama_server)
    assert error.value.code == code and error.value.retryable == retryable
    assert "PRIVATE_PROVIDER_ERROR" not in str(error.value)


@pytest.mark.parametrize("url", ["https://remote.example", "http://127.0.0.1/path", "http://user:pass@localhost", "http://localhost?x=1"])
def test_provider_settings_reject_nonlocal_or_ambiguous_urls(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ollama_base_url=url)


@pytest.mark.parametrize("failure,code", [(URLError("refused"), "OLLAMA_UNAVAILABLE"),
                                        (TimeoutError("timeout"), "OLLAMA_TIMEOUT")])
def test_ollama_connection_failures_are_retryable_without_inventing_output(source, monkeypatch, failure, code):
    class BrokenConnection:
        def open(self, *args, **kwargs):
            raise failure
    monkeypatch.setattr("autonomous_engineering.infrastructure.model_providers.build_opener", lambda *args: BrokenConnection())
    provider = OllamaPlanProvider(Settings(_env_file=None, ollama_model="fixture-model"))
    with pytest.raises(PlanningError) as error:
        Planner(provider).plan(RepositoryReader(source), TaskRequest(repository_path=str(source), user_request="Fix login"),
                               RepositoryAnalysis(languages=(), architecture_summary="Fixture"))
    assert error.value.code == code and error.value.retryable


def test_model_cannot_fabricate_reader_provenance(source):
    class InventedEvidence:
        def generate(self, context):
            values = fixture_plan().model_dump()
            values.update(context_files=("never-read.py",), limitations=("Invented evidence",))
            return ImplementationPlan.model_validate(values)
    result = Planner(InventedEvidence()).plan(RepositoryReader(source),
        TaskRequest(repository_path=str(source), user_request="Fix login"),
        RepositoryAnalysis(languages=(), architecture_summary="Fixture", relevant_files=("app.py",)))
    assert result.context_files == ("app.py",)
    assert "Invented evidence" not in result.limitations


def test_draft_normalization_is_explicit_and_keeps_proposed_paths_for_review(source):
    nested = source / "src" / "engine"
    nested.mkdir(parents=True)
    (nested / "state.py").write_text("state = True", encoding="utf-8")
    class Repetitive:
        def generate(self, context):
            return ImplementationPlan(problem_interpretation="Fixture", steps=(
                {"description": "Inspect state", "files": ("engine/state.py",)},
                {"description": "Inspect state", "files": ("engine/state.py",)},
                {"description": "Propose new test", "files": ("tests/new_test.py",)},
            ), tests_to_run=("Run focused tests",))
    result = Planner(Repetitive()).plan(RepositoryReader(source),
        TaskRequest(repository_path=str(source), user_request="Inspect state"),
        RepositoryAnalysis(languages=(), architecture_summary="Fixture", relevant_files=("src/engine/state.py",)))
    assert len(result.steps) == 2
    assert result.steps[0].files == ("src/engine/state.py",)
    assert result.steps[1].files == ("tests/new_test.py",)
    assert any("Repeated identical" in message for message in result.limitations)
    assert any("shortened file references" in message for message in result.limitations)
    assert any("tests/new_test.py" in message for message in result.limitations)
    assert not (source / "tests" / "new_test.py").exists()


def test_ambiguous_short_path_is_not_guessed(source):
    for prefix in ("one", "two"):
        (source / prefix).mkdir()
        (source / prefix / "state.py").write_text("state = True", encoding="utf-8")
    class Ambiguous:
        def generate(self, context):
            return ImplementationPlan(problem_interpretation="Fixture", steps=(
                {"description": "Inspect state", "files": ("state.py",)},
            ), tests_to_run=("Check state",))
    result = Planner(Ambiguous()).plan(RepositoryReader(source),
        TaskRequest(repository_path=str(source), user_request="Inspect"),
        RepositoryAnalysis(languages=(), architecture_summary="Fixture"))
    assert result.steps[0].files == ("state.py",)
    assert any("not present" in message for message in result.limitations)


@pytest.mark.parametrize("model", ["model:cloud", "model-cloud", " "])
def test_local_provider_rejects_cloud_tags_and_blank_models(model):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ollama_model=model)
