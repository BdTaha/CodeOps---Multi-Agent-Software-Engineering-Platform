"""Real subprocess evidence and explicit test-execution authorization."""

from pathlib import Path

import pytest

from autonomous_engineering.agents.developer import approval_identity
from autonomous_engineering.agents.tester import Tester as AgentTester
from autonomous_engineering.infrastructure.test_process import LocalTestProcess
from autonomous_engineering.tools.repository import RepositoryError
from autonomous_engineering.workflows.development import develop_approved
from autonomous_engineering.workflows.state import WorkflowState
from test_developer import planned, FixtureDeveloper


def suite(root: Path, body: str):
    tests = root / "tests"
    tests.mkdir(exist_ok=True)
    (tests / "test_fixture.py").write_text("import unittest, os, time\nclass Fixture(unittest.TestCase):\n    def test_fixture(self):\n" + body, encoding="utf-8")


def test_real_suite_passes_and_keeps_counts_unknown(planned):
    state, storage, _ = planned
    suite(Path(state.workspace_path), "        from app import greet\n        self.assertEqual(greet('Ada'), 'Hello Ada')\n")
    result = AgentTester(LocalTestProcess()).run(state, storage)
    assert result.outcome == "passed"
    assert result.counts is None
    assert result.executions[0].exit_code == 0
    assert "Ran 1 test" in result.executions[0].output_summary
    assert result.executions[0].duration_seconds > 0


def test_real_assertion_failure_is_not_execution_error(planned):
    state, storage, _ = planned
    suite(Path(state.workspace_path), "        self.assertEqual(1, 2)\n")
    result = AgentTester(LocalTestProcess()).run(state, storage)
    assert result.outcome == "failed"
    assert "AssertionError" in result.executions[0].output_summary
    assert result.executions[0].error is None


def test_missing_tests_are_skipped_without_launch(planned):
    state, storage, _ = planned
    class Never:
        def run(self, root):
            raise AssertionError("No process should run")
    result = AgentTester(Never()).run(state, storage)
    assert result.outcome == "skipped" and result.executions == ()


def test_zero_collected_tests_never_pass(planned):
    state, storage, _ = planned
    root = Path(state.workspace_path)
    (root / "tests").mkdir()
    (root / "tests" / "test_empty.py").write_text("# No tests\n")
    result = AgentTester(LocalTestProcess()).run(state, storage)
    assert result.outcome == "failed"
    assert result.executions[0].exit_code == 5


def test_timeout_stops_process_and_records_error(planned):
    state, storage, _ = planned
    suite(Path(state.workspace_path), "        time.sleep(10)\n")
    result = AgentTester(LocalTestProcess(timeout_seconds=0.3)).run(state, storage)
    assert result.outcome == "error"
    assert result.executions[0].timed_out
    assert result.executions[0].duration_seconds < 8


def test_output_flood_stops_and_preserves_bounded_excerpt(planned):
    state, storage, _ = planned
    suite(Path(state.workspace_path), "        print('x' * 100000, flush=True)\n        time.sleep(10)\n")
    result = AgentTester(LocalTestProcess(timeout_seconds=5, output_limit=2048)).run(state, storage)
    assert result.outcome == "error"
    assert "output exceeded" in result.executions[0].error
    assert len(result.executions[0].output_summary) <= 3000


def test_host_provider_secrets_are_not_inherited(planned, monkeypatch):
    state, storage, _ = planned
    monkeypatch.setenv("ASE_TEST_SECRET", "fixture-secret")
    monkeypatch.setenv("PYTHONPATH", "fixture-host-path")
    suite(Path(state.workspace_path), "        self.assertNotIn('ASE_TEST_SECRET', os.environ)\n        self.assertNotIn('PYTHONPATH', os.environ)\n")
    assert AgentTester(LocalTestProcess()).run(state, storage).outcome == "passed"


def test_wrong_workspace_is_denied_before_launch(planned):
    state, storage, source = planned
    values = state.model_dump()
    values["workspace_path"] = str(source)
    with pytest.raises(RepositoryError, match="identity"):
        AgentTester(LocalTestProcess()).run(WorkflowState.model_validate(values), storage)


def test_development_and_real_tests_preserve_source_and_require_review(planned):
    state, storage, source = planned
    suite(Path(state.workspace_path), "        from app import greet\n        self.assertEqual(greet(' Ada '), 'Hello Ada')\n")
    result = develop_approved(state, storage, approval_identity(state, storage), FixtureDeveloper(), test_process=LocalTestProcess())
    assert result.tests.outcome == "passed"
    assert result.executions[1].agent == "tester"
    assert result.executions[1].status == "succeeded"
    assert result.errors[-1].code == "REVIEW_NOT_CONFIGURED"
    assert result.task.status == "failed" and result.review is None
    assert source.joinpath("app.py").read_text().endswith("+ name\n")


def test_failed_tests_record_failed_agent_and_no_review(planned):
    state, storage, _ = planned
    suite(Path(state.workspace_path), "        self.fail('fixture failure')\n")
    result = develop_approved(state, storage, approval_identity(state, storage), FixtureDeveloper(), test_process=LocalTestProcess())
    assert result.tests.outcome == "failed"
    assert result.executions[1].status == "failed"
    assert result.errors[-1].code == "TESTS_FAILED"
    assert result.review is None


def test_no_consent_never_executes_repository_code(planned):
    state, storage, _ = planned
    root = Path(state.workspace_path)
    suite(root, "        open('execution-marker', 'w').write('ran')\n")
    result = develop_approved(state, storage, approval_identity(state, storage), FixtureDeveloper())
    assert result.tests.outcome == "skipped"
    assert not root.joinpath("execution-marker").exists()


@pytest.mark.parametrize("timeout,limit", [(0, 65536), (301, 65536), (60, 0)])
def test_invalid_execution_bounds_rejected(timeout, limit):
    with pytest.raises(ValueError):
        LocalTestProcess(timeout_seconds=timeout, output_limit=limit)


@pytest.mark.parametrize("consent,expected", [(False, "skipped"), (True, "passed")])
def test_monitor_only_executes_with_explicit_choice(tmp_path, monkeypatch, consent, expected):
    from fastapi.testclient import TestClient
    from autonomous_engineering import monitor
    from autonomous_engineering.core.config import Settings
    from autonomous_engineering.domain.results import ImplementationPlan
    from autonomous_engineering.infrastructure.ollama import OllamaPlanProvider

    source = tmp_path / "source"
    source.mkdir()
    source.joinpath("app.py").write_text("value = 1\n")
    suite(source, "        from app import value\n        self.assertEqual(value, 2)\n")
    def plan(self, context):
        return ImplementationPlan(problem_interpretation="Fixture update", steps=(
            {"description": "Change value", "files": ("app.py",)},), tests_to_run=("Run unittest",))
    monkeypatch.setattr(OllamaPlanProvider, "generate", plan)
    monkeypatch.setattr(monitor.GatewayReviewProvider, "generate", lambda self, context: {"approved": True, "summary": "Fixture review", "findings": []})
    monkeypatch.setattr(monitor.GatewayDevelopmentProvider, "generate", lambda self, context: FixtureDeveloper([
        {"path": "app.py", "kind": "modified", "content": "value = 2\n", "summary": "Fixture change"}]).generate(context))
    config = Settings(_env_file=None, ollama_model="fixture:local", workspace_root=tmp_path / "workspaces")
    with TestClient(monitor.create_monitor_app(config), base_url="http://localhost") as client:
        assert client.post("/monitor/run", json={"repository_path": str(source), "user_request": "Fixture"}).status_code == 200
        token = client.get("/monitor/approval").json()["approval_id"]
        body = {"approval_id": token, "run_tests": consent}
        assert client.post("/monitor/develop", json=body, headers={"origin": "https://other.example"}).status_code == 403
        response = client.post("/monitor/develop", json=body)
        assert response.status_code == 200
        assert response.json()["tests"]["outcome"] == expected
        assert client.get("/monitor/activity").json() == {"run_id": None, "node": None}
        assert response.json()["task"]["status"] == ("succeeded" if consent else "failed")
        assert (response.json()["review"] is not None) == consent
        assert source.joinpath("app.py").read_text() == "value = 1\n"
        assert client.post("/monitor/develop", json=body).status_code == 409
