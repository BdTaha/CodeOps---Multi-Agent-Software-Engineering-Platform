"""Actual failed validation followed by failed generation must remain auditable."""
import hashlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_developer import planned, FixtureDeveloper
from test_reviewer import FixtureReview
from test_test_execution import suite
from test_durable_platform import queue_development
from autonomous_engineering.agents.developer import approval_identity, DevelopmentProposal
from autonomous_engineering.agents.planner import PlanningError
from autonomous_engineering.core.config import Settings
from autonomous_engineering.domain.results import ReviewResults, TestExecution
from autonomous_engineering.infrastructure.docker_tests import DockerTestProcess
from autonomous_engineering.infrastructure.task_store import TaskStore
from autonomous_engineering.infrastructure.test_process import LocalTestProcess
from autonomous_engineering.platform import create_platform_app
from autonomous_engineering.workflows.development import develop_approved
from autonomous_engineering.workflows.state import WorkflowState, WorkflowUpdate


class FailedRepair(FixtureDeveloper):
    def generate(self, context):
        if context.attempt > 1:
            raise PlanningError('INVALID_DEVELOPMENT', 'Repair returned invalid structured output.')
        return super().generate(context)


class CountingProcess:
    def __init__(self, process):
        self.process = process
        self.calls = 0

    def run(self, root):
        self.calls += 1
        return self.process.run(root)


def run_failed_repair(planned, process, on_node_completed=None):
    state, storage, _ = planned
    suite(Path(state.workspace_path), '        self.fail("original deterministic failure")\n')
    checkpoints = []

    def completed(node, snapshot):
        checkpoints.append((node, snapshot))
        if on_node_completed:
            on_node_completed(node, snapshot)

    result = develop_approved(state, storage, approval_identity(state, storage), FailedRepair(),
        test_process=process, review_provider=FixtureReview(), allow_repairs=True,
        on_node_completed=completed)
    return result, checkpoints


def assert_retained(result, checkpoints):
    first_code = next(snapshot for node, snapshot in checkpoints if node == 'develop_implementation')
    first_tests = next(snapshot for node, snapshot in checkpoints if node == 'run_tests')
    assert result.task.status == 'failed'
    assert result.development_attempts == 2
    assert result.development == first_code.development
    assert result.changes == result.development.changes == first_code.changes
    assert result.development.diff and len(result.changes) == 3
    assert result.tests == first_tests.tests
    execution = result.tests.executions[0]
    assert result.tests.outcome == 'failed'
    assert execution.command and execution.exit_code != 0
    assert execution.duration_seconds > 0
    assert 'original deterministic failure' in execution.output_summary
    assert not execution.timed_out and execution.error is None
    assert result.tests.suspected_cause and result.tests.recommendation
    assert result.review is None
    assert [error.code for error in result.errors] == ['TESTS_FAILED', 'INVALID_DEVELOPMENT']
    assert result.report.outcome == 'failed'
    assert result.report.summary == result.errors[-1].message
    assert [(record.operation, record.status) for record in result.executions
            if record.status == 'failed'] == [('run_tests', 'failed'), ('develop_implementation', 'failed')]


def test_failed_repair_retains_actual_test_and_multifile_artifact(planned):
    process = CountingProcess(LocalTestProcess())
    result, checkpoints = run_failed_repair(planned, process)
    assert_retained(result, checkpoints)
    assert process.calls == 1  # Do not overwrite Tests A after generation fails.
    for path, digest in result.development.content_hashes.items():
        file = Path(result.workspace_path, path)
        assert digest == (hashlib.sha256(file.read_bytes()).hexdigest() if file.exists() else None)
    assert result.development.original_files['app.py'] == planned[2].joinpath('app.py').read_bytes().decode('utf-8')
    assert planned[2].joinpath('app.py').read_text().endswith('+ name\n')


def test_successful_replacement_invalidates_old_tests_before_testing_new_code(planned):
    state, storage, _ = planned
    suite(Path(state.workspace_path), "        from app import greet\n        self.assertEqual(greet(' Ada '), 'Hello Ada')\n")
    checkpoints = []

    class Repair:
        def generate(self, context):
            if context.attempt == 2:
                assert context.tests.outcome == 'failed'
            content = "def greet(name):\n    return 'Wrong'\n" if context.attempt == 1 else "def greet(name):\n    return 'Hello ' + name.strip()\n"
            return DevelopmentProposal(explanation='Correct greeting', edits=[dict(
                path='app.py', kind='modified', content=content, summary='Greeting change')])

    result = develop_approved(state, storage, approval_identity(state, storage), Repair(),
        test_process=LocalTestProcess(), review_provider=FixtureReview(), allow_repairs=True,
        on_node_completed=lambda node, snapshot: checkpoints.append((node, snapshot)))
    second_code = [snapshot for node, snapshot in checkpoints if node == 'develop_implementation'][1]
    assert second_code.tests is second_code.review is second_code.report is None
    tests = [snapshot.tests for node, snapshot in checkpoints if node == 'run_tests']
    assert [value.outcome for value in tests] == ['failed', 'passed']
    assert result.task.status == 'succeeded' and result.development_attempts == 2
    assert result.tests == tests[1] and result.tests != tests[0]
    assert result.development == second_code.development
    assert 'Wrong' not in result.development.diff


def test_failed_repair_checkpoints_reopen_and_full_api_retains_artifacts(planned, tmp_path):
    state, storage, source = planned
    url = 'sqlite:///' + str(tmp_path / 'retention.db')
    store = TaskStore(url)
    task_id = queue_development(store, state, storage)
    assert store.claim('retention-worker', 300)

    def persist(node, snapshot):
        store.checkpoint(task_id, 'retention-worker', snapshot, node=node,
            phase='failed' if snapshot.task.status.terminal else None)
        restored = WorkflowState.model_validate(store.get(task_id)['snapshot'])
        assert restored == snapshot

    result, checkpoints = run_failed_repair(planned, LocalTestProcess(), persist)
    assert_retained(result, checkpoints)
    assert WorkflowState.model_validate_json(result.model_dump_json()) == result
    store.close()
    reopened = TaskStore(url)
    config = Settings(_env_file=None, workspace_root=storage, repository_root=source.parent)
    with TestClient(create_platform_app(config, reopened)) as client:
        response = client.get(f'/tasks/{task_id}/result')
        assert response.status_code == 200
        assert WorkflowState.model_validate(response.json()) == result
        full = client.get(f'/tasks/{task_id}').json()['snapshot']
        assert full['development']['diff'] == result.development.diff
        assert full['tests']['executions'][0]['output_summary'] == result.tests.executions[0].output_summary
        assert full['errors'][-1]['code'] == 'INVALID_DEVELOPMENT'
        file = client.get(f'/tasks/{task_id}/file', params={'path': 'new.py'})
        assert file.status_code == 200 and 'new = True' in file.text
    reopened.close()


def test_attempt_error_preserves_review_and_test_error_metadata(planned):
    from autonomous_engineering.domain.results import TestResults
    from autonomous_engineering.domain.execution import ExecutionError
    result, checkpoints = run_failed_repair(planned, LocalTestProcess())
    state = next(snapshot for node, snapshot in checkpoints if node == 'run_tests')
    review = ReviewResults(approved=False, summary='Needs correction', findings=[dict(
        severity='medium', description='Behavior is incorrect', recommended_fix='Correct behavior')])
    state = state.apply(WorkflowUpdate(review=review))
    retained = state.apply(WorkflowUpdate(development_attempt_increment=1,
        errors=[ExecutionError(code='INVALID_DEVELOPMENT', message='Invalid repair')]))
    assert retained.review == review and retained.tests == state.tests
    assert retained.development == state.development
    error_tests = TestResults(outcome='error', summary='Command timed out', suspected_cause='Timeout',
        recommendation='Inspect hang', executions=[TestExecution(command=['python', '-m', 'unittest'],
        exit_code=None, duration_seconds=2, output_summary='bounded partial output', timed_out=True, error='Timed out')])
    state = state.apply(WorkflowUpdate(tests=error_tests))
    assert state.apply(WorkflowUpdate(development_attempt_increment=1)).tests == error_tests
    # Artifact-only replacement also invalidates downstream evidence.
    replaced = state.apply(WorkflowUpdate(development=state.development))
    assert replaced.tests is replaced.review is replaced.report is None


def test_failed_repair_after_rejected_review_preserves_both_validations(planned):
    state, storage, _ = planned
    suite(Path(state.workspace_path), '        self.assertTrue(True)\n')
    reviews = []

    class Reject:
        def generate(self, context):
            review = ReviewResults(approved=False, summary='Initial code needs correction', findings=[dict(
                severity='medium', description='Incorrect behavior', recommended_fix='Correct the implementation',
                file='app.py', line=2, evidence="return 'Hello ' + name.strip()")])
            reviews.append(review)
            return review

    reviewer = Reject()
    checkpoints = []
    process = CountingProcess(LocalTestProcess())
    result = develop_approved(state, storage, approval_identity(state, storage), FailedRepair(),
        test_process=process, review_provider=reviewer, allow_repairs=True,
        on_node_completed=lambda node, snapshot: checkpoints.append((node, snapshot)))
    reviewed = next(snapshot for node, snapshot in checkpoints if node == 'review_changes')
    assert result.task.status == 'failed' and result.development_attempts == 2
    assert result.tests == reviewed.tests and result.tests.outcome == 'passed'
    assert result.review == reviewed.review == reviews[0] and not result.review.approved
    assert len(reviews) == process.calls == 1
    assert result.development == reviewed.development
    assert result.errors[-1].code == 'INVALID_DEVELOPMENT'


@pytest.mark.skipif(not os.environ.get('ASE_INTEGRATION_DOCKER'), reason='Explicit Docker integration opt-in')
def test_docker_failure_then_invalid_repair_retains_historical_api_evidence(planned, tmp_path):
    config = Settings(_env_file=None, docker_executable=os.environ.get('ASE_DOCKER_EXECUTABLE', 'docker'))
    process = CountingProcess(DockerTestProcess(config))
    result, checkpoints = run_failed_repair(planned, process)
    assert_retained(result, checkpoints)
    assert process.calls == 1
    command = result.tests.executions[0].command
    assert '--network=none' in command and '--read-only' in command
    assert any('readonly' in part for part in command)
    store = TaskStore('sqlite:///' + str(tmp_path / 'docker-history.db'))
    task_id = queue_development(store, planned[0], planned[1])
    assert store.claim('docker-history-worker', 300)
    store.checkpoint(task_id, 'docker-history-worker', result, phase='failed')
    config = Settings(_env_file=None, workspace_root=planned[1], repository_root=planned[2].parent)
    with TestClient(create_platform_app(config, store)) as client:
        response = client.get(f'/tasks/{task_id}/result')
        assert response.status_code == 200
        snapshot = response.json()
        assert snapshot['development']['diff'] == result.development.diff
        assert snapshot['tests']['executions'][0]['output_summary'] == result.tests.executions[0].output_summary
        assert snapshot['errors'][-1]['code'] == 'INVALID_DEVELOPMENT'
    store.close()
