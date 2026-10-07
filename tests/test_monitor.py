import asyncio
import json

from fastapi.testclient import TestClient

from autonomous_engineering.core.config import Settings
from autonomous_engineering.domain.tasks import TaskRecord, TaskRequest
from autonomous_engineering.monitor import create_monitor_app
from autonomous_engineering.workflows.state import WorkflowState
from autonomous_engineering.workflows.streaming import ProgressEvent, stream_workflow


def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "app.py").write_text("def login(): return True\n", encoding="utf-8")
    return root


def client(tmp_path):
    settings = Settings(_env_file=None, environment="test", workspace_root=tmp_path / "snapshots", ollama_model=None)
    return TestClient(create_monitor_app(settings), base_url="http://localhost")


def parse_events(response):
    return [ProgressEvent.model_validate(json.loads(frame[6:]))
            for frame in response.text.strip().split("\n\n") if frame.startswith("data: ")]


def test_monitor_stream_has_real_starts_completions_and_final_analysis(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    root = source(tmp_path)
    with client(tmp_path) as browser:
        page = browser.get("/")
        assert page.status_code == 200
        assert "Replay trace" in page.text
        assert browser.get("/health").json() == {"status": "ok"}
        response = browser.post("/monitor/run", json={"repository_path": str(root), "user_request": "Fix login"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = parse_events(response)
        assert events[0].kind == "run_started"
        assert events[-1].kind == "run_finished"
        assert [e.kind for e in events[1:-1]] == ["node_started", "node_completed"] * 5
        assert [e.node for e in events if e.kind == "node_started"] == [
            "supervisor", "prepare_workspace", "analyze_repository", "plan_implementation", "finalize_failure",
        ]
        assert events[-1].snapshot.analysis.inspected_file_count == 1
        assert events[-1].snapshot.errors[-1].code == "PLANNER_NOT_CONFIGURED"
        second = browser.post("/monitor/run", json={"repository_path": str(root), "user_request": "Inspect"})
        assert second.status_code == 200
        assert parse_events(second)[-1].snapshot.run_id != events[-1].snapshot.run_id


def test_monitor_failed_source_and_input_validation(tmp_path) -> None:
    with client(tmp_path) as browser:
        response = browser.post("/monitor/run", json={"repository_path": str(tmp_path / "missing"), "user_request": "Inspect"})
        events = parse_events(response)
        assert events[-1].kind == "run_finished"
        assert events[-1].snapshot.errors[-1].code == "REPOSITORY_NOT_FOUND"
        assert len([e for e in events if e.kind == "node_completed"]) == 3
        assert browser.post("/monitor/run", json={"repository_path": "", "user_request": ""}).status_code == 422


def test_monitor_rejects_untrusted_host_and_cross_origin_run(tmp_path) -> None:
    with client(tmp_path) as browser:
        assert browser.get("/", headers={"host": "external.example"}).status_code == 400
        response = browser.post("/monitor/run", headers={"origin": "https://external.example"},
                                json={"repository_path": ".", "user_request": "Inspect"})
        assert response.status_code == 403


def test_unexpected_node_error_is_reported_without_leaking_exception(tmp_path, monkeypatch) -> None:
    from autonomous_engineering.workflows import graph as graph_module

    def broken(state):
        raise RuntimeError("PRIVATE_EXCEPTION_TEXT")

    monkeypatch.setattr(graph_module, "supervisor", broken)

    async def collect():
        initial = WorkflowState(task=TaskRecord(request=TaskRequest(repository_path=".", user_request="Inspect")))
        return [event async for event in stream_workflow(initial, workspace_root=tmp_path)]

    events = asyncio.run(collect())
    assert events[-1].kind == "run_error"
    assert "PRIVATE_EXCEPTION_TEXT" not in events[-1].model_dump_json()
    assert not any(e.kind == "run_finished" for e in events)


def test_workspace_file_api_reads_only_latest_managed_snapshot(tmp_path):
    root = source(tmp_path)
    root.joinpath(".env").write_text("PRIVATE_FIXTURE_SECRET")
    with client(tmp_path) as browser:
        response = browser.post("/monitor/run", json={"repository_path": str(root), "user_request": "Inspect"})
        snapshot = parse_events(response)[-1].snapshot
        prefix = f"/monitor/workspace/{snapshot.run_id}"
        assert browser.get(prefix + "/files").json()["files"] == ["app.py"]
        result = browser.get(prefix + "/file", params={"path": "app.py"})
        assert result.status_code == 200
        assert result.json()["content"] == root.joinpath("app.py").read_bytes().decode()
        assert result.headers["cache-control"] == "no-store"
        for path in ("../.env", ".env", str(root / "app.py")):
            denied = browser.get(prefix + "/file", params={"path": path})
            assert denied.status_code == 400
            assert "PRIVATE_FIXTURE_SECRET" not in denied.text
        browser.post("/monitor/run", json={"repository_path": str(root), "user_request": "Inspect again"})
        assert browser.get(prefix + "/files").status_code == 404


def test_workspace_file_api_rejects_unknown_and_invalid_run(tmp_path):
    from uuid import uuid4
    with client(tmp_path) as browser:
        assert browser.get(f"/monitor/workspace/{uuid4()}/files").status_code == 404
        assert browser.get("/monitor/workspace/not-a-uuid/files").status_code == 422
