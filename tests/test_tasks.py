from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from autonomous_engineering.domain.tasks import (
    InvalidTaskTransition,
    TaskRecord,
    TaskRequest,
    TaskStatus,
)

NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)
EXPECTED_TRANSITIONS = {
    (TaskStatus.PENDING, TaskStatus.RUNNING),
    (TaskStatus.PENDING, TaskStatus.CANCELLED),
    (TaskStatus.RUNNING, TaskStatus.SUCCEEDED),
    (TaskStatus.RUNNING, TaskStatus.FAILED),
    (TaskStatus.RUNNING, TaskStatus.CANCELLED),
}


def make_task() -> TaskRecord:
    return TaskRecord(
        request=TaskRequest(repository_path="C:/source/project", user_request="Fix a bug"),
        created_at=NOW,
        updated_at=NOW,
    )


def task_in_status(status: TaskStatus) -> TaskRecord:
    task = make_task()
    if status == TaskStatus.PENDING:
        return task
    if status == TaskStatus.CANCELLED:
        return task.transition(status, at=NOW + timedelta(seconds=2))
    task = task.transition(TaskStatus.RUNNING, at=NOW + timedelta(seconds=1))
    if status != TaskStatus.RUNNING:
        task = task.transition(status, at=NOW + timedelta(seconds=2))
    return task


@pytest.mark.parametrize("source", list(TaskStatus))
@pytest.mark.parametrize("target", list(TaskStatus))
def test_all_lifecycle_transitions(source, target) -> None:
    task = task_in_status(source)
    if (source, target) not in EXPECTED_TRANSITIONS:
        with pytest.raises(InvalidTaskTransition):
            task.transition(target, at=NOW + timedelta(seconds=3))
        return
    result = task.transition(target, at=NOW + timedelta(seconds=3))
    assert result.status == target
    assert task.status == source
    assert result.task_id == task.task_id
    assert result.finished_at == (result.updated_at if target.terminal else None)


@pytest.mark.parametrize("field", ["repository_path", "user_request"])
def test_blank_task_input_is_rejected(field) -> None:
    values = {"repository_path": "repo", "user_request": "Fix a bug", field: " \t"}
    with pytest.raises(ValidationError):
        TaskRequest(**values)


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        TaskRequest(repository_path="repo", user_request="Fix", user_requset="Typo")


def test_transition_rejects_naive_or_backwards_timestamp() -> None:
    task = make_task().transition(TaskStatus.RUNNING, at=NOW + timedelta(seconds=2))
    for timestamp in (NOW, NOW.replace(tzinfo=None)):
        with pytest.raises(ValueError):
            task.transition(TaskStatus.FAILED, at=timestamp)


@pytest.mark.parametrize(
    "values",
    [
        {"status": "running"},
        {"status": "pending", "started_at": NOW},
        {"status": "succeeded", "finished_at": NOW},
        {"status": "cancelled", "finished_at": NOW - timedelta(seconds=1)},
    ],
)
def test_invalid_lifecycle_snapshot_cannot_be_deserialized(values) -> None:
    data = make_task().model_dump()
    data.update(values)
    with pytest.raises(ValidationError):
        TaskRecord.model_validate(data)


def test_task_json_round_trip_and_utc_normalization() -> None:
    task = make_task().transition(
        TaskStatus.RUNNING,
        at=NOW.astimezone(timezone(timedelta(hours=1))),
    )
    assert task.started_at.utcoffset() == timedelta(0)
    assert TaskRecord.model_validate_json(task.model_dump_json()) == task
    with pytest.raises(ValidationError):
        task.status = TaskStatus.FAILED
