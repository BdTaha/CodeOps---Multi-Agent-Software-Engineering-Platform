"""Run the local repository analysis and draft planning workflow."""

import argparse
import asyncio

from pydantic import ValidationError

from autonomous_engineering.core.config import Settings
from autonomous_engineering.core.logging import configure_logging
from autonomous_engineering.domain.tasks import TaskRecord, TaskRequest, TaskStatus
from autonomous_engineering.workflows.runner import run_workflow
from autonomous_engineering.workflows.state import WorkflowState


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, help="Source repository reference")
    parser.add_argument("--request", required=True, help="Engineering task description")
    args = parser.parse_args()
    try:
        settings = Settings()
        request = TaskRequest(repository_path=args.repository, user_request=args.request)
    except ValidationError as exc:
        parser.error(str(exc))
    configure_logging(settings.log_level)
    result = asyncio.run(run_workflow(WorkflowState(task=TaskRecord(request=request)), settings=settings))
    print(result.model_dump_json(indent=2))
    # A valid orchestration run can finish with an unsuccessful engineering task.
    return 0 if result.task.status == TaskStatus.SUCCEEDED else 2


if __name__ == "__main__":
    raise SystemExit(main())
