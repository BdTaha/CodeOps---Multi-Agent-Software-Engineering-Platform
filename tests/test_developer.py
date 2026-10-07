"""Development boundary tests use explicit fixture approval, never runtime plans."""

from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from autonomous_engineering.agents.developer import (
    Developer, DevelopmentProposal, DevelopmentContext, approval_identity,
)
from autonomous_engineering.agents.planner import PlanningError
from autonomous_engineering.core.config import Settings
from autonomous_engineering.domain.results import ImplementationPlan
from autonomous_engineering.domain.tasks import TaskRecord, TaskRequest, TaskStatus
from autonomous_engineering.infrastructure.workspaces import WorkspacePreparer
from autonomous_engineering.infrastructure.ollama_developer import OllamaDevelopmentProvider
from autonomous_engineering.monitor import create_monitor_app
from autonomous_engineering.tools.repository import RepositoryError
from autonomous_engineering.workflows.development import develop_approved
from autonomous_engineering.workflows.state import WorkflowState, WorkflowUpdate
from test_planner import ollama_server  # Reuse the local HTTP transport fixture.


@pytest.fixture
def planned(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("def greet(name):\n    return 'Hello ' + name\n", encoding="utf-8")
    storage = tmp_path / "workspaces"
    state = WorkflowState(task=TaskRecord(request=TaskRequest(repository_path=str(source), user_request="Trim names")))
    workspace = WorkspacePreparer(storage).prepare(source, state.run_id)
    values = state.model_dump()
    values["workspace_path"] = str(workspace.root)
    state = WorkflowState.model_validate(values).apply(WorkflowUpdate(status=TaskStatus.RUNNING,
        plan=ImplementationPlan(problem_interpretation="Fixture: trim whitespace", steps=(
            {"description": "Trim names in greeting", "files": ("app.py", "new.py", "old.py")},), tests_to_run=("Check greetings",))))
    (workspace.root / "old.py").write_text("old = True\n")
    return state, storage, source


class FixtureDeveloper:
    def __init__(self, edits=None):
        self.called = False
        self.context = None
        self.edits = edits or [
            {"path": "app.py", "kind": "modified", "content": "def greet(name):\n    return 'Hello ' + name.strip()\n", "summary": "Trim input"},
            {"path": "new.py", "kind": "created", "content": "new = True\n", "summary": "Fixture creation"},
            {"path": "old.py", "kind": "deleted", "content": None, "summary": "Fixture deletion"},
        ]

    def generate(self, context):
        self.called = True
        self.context = context
        return DevelopmentProposal(explanation="Fixture edits", edits=self.edits)


def test_approved_changes_are_real_and_source_stays_unchanged(planned):
    state, storage, source = planned
    provider = FixtureDeveloper()
    token = approval_identity(state, storage)
    result = develop_approved(state, storage, token, provider)
    workspace = Path(state.workspace_path)
    assert workspace.joinpath("app.py").read_text().endswith("name.strip()\n")
    assert workspace.joinpath("new.py").read_text() == "new = True\n"
    assert not workspace.joinpath("old.py").exists()
    assert source.joinpath("app.py").read_text().endswith("+ name\n")
    assert not source.joinpath("new.py").exists()
    assert result.development.approval_id == token
    assert result.development.approved_at.tzinfo is not None
    assert "+    return 'Hello ' + name.strip()" in result.development.diff
    assert "/dev/null" in result.development.diff
    assert result.changes == result.development.changes
    assert result.executions[0].agent == "developer"
    assert result.executions[0].status == "succeeded"
    assert result.errors[-1].code == "TEST_VALIDATION_REQUIRED"
    assert result.task.status == "failed" and result.tests.outcome == "skipped" and result.review is None
    assert provider.context.files["app.py"] == source.joinpath("app.py").read_bytes().decode()


@pytest.mark.parametrize("mutation", ["file", "new_file", "plan", "task", "run"])
def test_approval_binds_plan_task_run_and_snapshot(planned, mutation):
    state, storage, _ = planned
    token = approval_identity(state, storage)
    if mutation in {"file", "new_file"}:
        Path(state.workspace_path, "app.py" if mutation == "file" else "extra.py").write_text("changed\n")
    else:
        values = state.model_dump()
        if mutation == "plan":
            values["plan"]["steps"][0]["description"] = "Different plan"
        elif mutation == "task":
            values["task"]["request"]["user_request"] = "Different request"
        else:
            from uuid import uuid4
            values["run_id"] = uuid4()
        state = WorkflowState.model_validate(values)
    provider = FixtureDeveloper()
    with pytest.raises(RepositoryError):
        Developer(provider).develop(state, storage, token)
    assert not provider.called


@pytest.mark.parametrize("path", [".env", ".git/config", "NUL.py", "CON/file.py", "app.py.", ".venv/x.py", "folder./x.py", "folder?/x.py", "bad\n.py"])
def test_denied_plan_paths_never_reach_provider(planned, path):
    state, storage, _ = planned
    plan = ImplementationPlan(problem_interpretation="Fixture", steps=({"description": "Edit", "files": (path,)},), tests_to_run=("Check",))
    state = state.apply(WorkflowUpdate(plan=plan))
    provider = FixtureDeveloper()
    with pytest.raises(RepositoryError, match="paths|Links|links|excluded|Excluded"):
        Developer(provider).develop(state, storage, approval_identity(state, storage))
    assert not provider.called


@pytest.mark.parametrize("bad_edit", [
    {"path": "outside.py", "kind": "created", "content": "x\n", "summary": "Outside plan"},
    {"path": "app.py", "kind": "created", "content": "x\n", "summary": "Wrong kind"},
    {"path": "new.py", "kind": "modified", "content": "x\n", "summary": "Wrong kind"},
])
def test_entire_proposal_validated_before_writes(planned, bad_edit):
    state, storage, source = planned
    provider = FixtureDeveloper([{"path": "app.py", "kind": "modified", "content": "changed\n", "summary": "First edit"}, bad_edit])
    result = develop_approved(state, storage, approval_identity(state, storage), provider)
    assert result.development is None
    assert Path(state.workspace_path, "app.py").read_text() == source.joinpath("app.py").read_text()
    assert not Path(state.workspace_path, "new.py").exists()


def test_snapshot_change_during_generation_prevents_writes(planned):
    state, storage, _ = planned
    token = approval_identity(state, storage)
    class Mutating(FixtureDeveloper):
        def generate(self, context):
            Path(state.workspace_path, "app.py").write_text("external change\n")
            return super().generate(context)
    result = develop_approved(state, storage, token, Mutating())
    assert result.errors[-1].code == "STALE_APPROVAL"
    assert Path(state.workspace_path, "app.py").read_text() == "external change\n"


def test_write_failure_rolls_back_earlier_edits(planned, monkeypatch):
    state, storage, source = planned
    original_write = Path.write_text
    def failing_write(path, *args, **kwargs):
        if path.name == "new.py":
            raise OSError("Fixture disk failure")
        return original_write(path, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", failing_write)
    result = develop_approved(state, storage, approval_identity(state, storage), FixtureDeveloper())
    assert result.errors[-1].code == "WORKSPACE_WRITE_FAILED"
    assert Path(state.workspace_path, "app.py").read_text() == source.joinpath("app.py").read_text()
    assert not Path(state.workspace_path, "new.py").exists()


def test_large_full_file_fails_instead_of_truncating(planned):
    state, storage, _ = planned
    Path(state.workspace_path, "app.py").write_text("x" * 33000)
    provider = FixtureDeveloper()
    with pytest.raises(RepositoryError, match="context budget"):
        Developer(provider).develop(state, storage, approval_identity(state, storage))
    assert not provider.called


def test_invalid_provider_contract_records_failure(planned):
    state, storage, _ = planned
    class Invalid:
        def generate(self, context):
            return {"explanation": "Bad", "edits": [{"path": "../escape.py", "kind": "created", "content": "x", "summary": "Bad"}]}
    result = develop_approved(state, storage, approval_identity(state, storage), Invalid())
    assert result.errors[-1].code == "INVALID_DEVELOPMENT"
    assert result.development is None


def test_replacing_plan_invalidates_development_artifact(planned):
    state, storage, _ = planned
    artifact = Developer(FixtureDeveloper()).develop(state, storage, approval_identity(state, storage))
    developed = state.apply(WorkflowUpdate(changes=artifact.changes, development=artifact))
    assert developed.apply(WorkflowUpdate(plan=state.plan)).development is None


def test_output_byte_budget_rejects_before_application(planned):
    state, storage, _ = planned
    state = state.apply(WorkflowUpdate(plan=ImplementationPlan(problem_interpretation="Fixture", steps=(
        {"description": "Create files", "files": ("one.py", "two.py")},), tests_to_run=("Check",))))
    provider = FixtureDeveloper([{"path": path, "kind": "created", "content": "界" * 32000, "summary": "Fixture"}
                                 for path in ("one.py", "two.py")])
    result = develop_approved(state, storage, approval_identity(state, storage), provider)
    assert result.errors[-1].code == "DEVELOPMENT_OUTPUT_LIMIT"
    assert not Path(state.workspace_path, "one.py").exists()


def test_diff_preserves_missing_newline_information(planned):
    state, storage, _ = planned
    provider = FixtureDeveloper([{"path": "app.py", "kind": "modified", "content": "replacement", "summary": "Fixture"}])
    artifact = Developer(provider).develop(state, storage, approval_identity(state, storage))
    assert "+replacement\n\\ No newline at end of file\n" in artifact.diff
    assert Path(state.workspace_path, "app.py").read_bytes() == b"replacement"


def test_wrong_storage_cannot_write_host_source(planned):
    state, storage, source = planned
    values = state.model_dump()
    values["workspace_path"] = str(source)
    state = WorkflowState.model_validate(values)
    with pytest.raises(RepositoryError, match="identity"):
        Developer(FixtureDeveloper()).develop(state, storage, "a" * 64)


def test_terminal_snapshot_cannot_be_reopened(planned):
    state, storage, _ = planned
    terminal = state.apply(WorkflowUpdate(status=TaskStatus.FAILED))
    with pytest.raises(RepositoryError, match="running"):
        develop_approved(terminal, storage, approval_identity(state, storage), FixtureDeveloper())


def test_monitor_explicit_single_use_approval_and_real_diff(tmp_path, monkeypatch):
    from autonomous_engineering.infrastructure import ollama
    from autonomous_engineering import monitor
    root = tmp_path / "source"
    root.mkdir()
    root.joinpath("app.py").write_text("before\n")
    class FixturePlanner:
        def generate(self, context):
            return ImplementationPlan(problem_interpretation="Fixture change", steps=(
                {"description": "Modify app", "files": ("app.py",)},), tests_to_run=("Check",))
    monkeypatch.setattr(ollama.OllamaPlanProvider, "generate", FixturePlanner().generate)
    monkeypatch.setattr(monitor.OllamaDevelopmentProvider, "generate", FixtureDeveloper([
        {"path": "app.py", "kind": "modified", "content": "after\n", "summary": "Fixture edit"}]).generate)
    settings = Settings(_env_file=None, ollama_model="fixture:local", workspace_root=tmp_path / "workspaces")
    with TestClient(create_monitor_app(settings), base_url="http://localhost") as client:
        assert client.get("/monitor/approval").json()["approval_id"] is None
        response = client.post("/monitor/run", json={"repository_path": str(root), "user_request": "Fixture"})
        assert response.status_code == 200
        approval = client.get("/monitor/approval").json()
        assert len(approval["approval_id"]) == 64
        assert root.joinpath("app.py").read_text() == "before\n"
        body = {"approval_id": approval["approval_id"]}
        assert client.post("/monitor/develop", json=body, headers={"origin": "https://external.example"}).status_code == 403
        result = client.post("/monitor/develop", json=body)
        assert result.status_code == 200
        assert "+after" in result.json()["development"]["diff"]
        assert root.joinpath("app.py").read_text() == "before\n"
        assert client.post("/monitor/develop", json=body).status_code == 409
        assert client.get("/monitor/approval").json()["approval_id"] is None


def test_developer_ollama_schema_and_full_file_context(planned, ollama_server):
    state, storage, _ = planned
    url, behavior, captured = ollama_server
    proposal = DevelopmentProposal(explanation="Fixture", edits=FixtureDeveloper().edits)
    behavior["body"] = {"done": True, "message": {"content": proposal.model_dump_json()}}
    provider = OllamaDevelopmentProvider(Settings(_env_file=None, ollama_base_url=url, ollama_model="fixture-model"))
    artifact = Developer(provider).develop(state, storage, approval_identity(state, storage))
    assert len(artifact.changes) == 3
    body = captured[0][1]
    files = json.loads(body['messages'][1]['content'])['files']
    assert body["format"] == provider.response_schema(DevelopmentContext(task=state.task.request,plan=state.plan,files=files))
    variants = body['format']['$defs']['FileEdit']['anyOf']
    for variant in variants:
        assert 'content' in variant['required']
        kind = variant['properties']['kind']['const']
        path = variant['properties']['path']['const']
        assert (kind == 'created') == (files[path] is None)
        assert variant['properties']['content']['type'] == ('null' if kind == 'deleted' else 'string')
    evidence = json.loads(body["messages"][1]["content"])
    assert evidence["files"]["app.py"].startswith("def greet")
    assert evidence["files"]["new.py"] is None
    assert "repository_path" not in evidence["task"]
    assert "COMPLETE replacement file" in body["messages"][0]["content"]


@pytest.mark.parametrize("payload", [
    {"done": True, "done_reason": "length", "message": {"content": "{}"}},
    {"done": True, "message": {"content": '{"explanation":"Bad","edits":[]}'}},
])
def test_developer_ollama_rejects_incomplete_or_invalid_edits(planned, ollama_server, payload):
    state, _, _ = planned
    url, behavior, _ = ollama_server
    behavior["body"] = payload
    provider = OllamaDevelopmentProvider(Settings(_env_file=None, ollama_base_url=url, ollama_model="fixture-model"))
    with pytest.raises(PlanningError) as error:
        provider.generate(DevelopmentContext(task=state.task.request, plan=state.plan, files={"app.py": "before\n"}))
    assert error.value.code == "INVALID_DEVELOPMENT"


def test_invalid_created_content_is_explained_without_leaking_source(planned, ollama_server):
    state, _, _ = planned
    url, behavior, _ = ollama_server
    behavior['body'] = {'done': True, 'prompt_eval_count': 100, 'eval_count': 20,
        'message': {'content': json.dumps({'explanation':'PRIVATE_SOURCE_TEXT','edits':[
            {'path':'new.py','kind':'created','content':None,'summary':'Create'}]})}}
    provider = OllamaDevelopmentProvider(Settings(_env_file=None,ollama_base_url=url,ollama_model='fixture-model'))
    with pytest.raises(PlanningError) as error:
        provider.generate(DevelopmentContext(task=state.task.request,plan=state.plan,files={'new.py':None}))
    assert 'edits.0' in str(error.value)
    assert 'PRIVATE_SOURCE_TEXT' not in str(error.value)
    assert provider.last_usage == {'model':'fixture-model','input_tokens':100,'output_tokens':20}


def test_unchanged_file_is_omitted_beside_real_creation(planned):
    state, storage, source = planned
    before = source.joinpath('app.py').read_bytes().decode()
    provider = FixtureDeveloper(edits=[
        dict(path='app.py',kind='modified',content=before,summary='Unchanged'),
        dict(path='new.py',kind='created',content='hello = True\n',summary='Create')])
    artifact = Developer(provider).develop(state,storage,approval_identity(state,storage))
    assert [c.path for c in artifact.changes] == ['new.py']
    assert 'app.py' not in artifact.diff
    assert source.joinpath('app.py').read_bytes().decode() == before


def test_all_unchanged_files_still_fail(planned):
    state, storage, source = planned
    provider = FixtureDeveloper(edits=[dict(path='app.py',kind='modified',
        content=source.joinpath('app.py').read_bytes().decode(),summary='Unchanged')])
    with pytest.raises(RepositoryError,match='do not change any file'):
        Developer(provider).develop(state,storage,approval_identity(state,storage))
