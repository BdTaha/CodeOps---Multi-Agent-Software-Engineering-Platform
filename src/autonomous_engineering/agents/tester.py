"""Deterministic test selection and interpretation of actual process evidence."""

from pathlib import Path
from typing import Protocol

from autonomous_engineering.agents.developer import workspace_reader
from autonomous_engineering.domain.results import TestExecution, TestOutcome, TestResults
from autonomous_engineering.workflows.state import WorkflowState


class TestProcess(Protocol):
    def run(self, root: Path) -> TestExecution: ...


class Tester:
    def __init__(self, process: TestProcess):
        self.process = process

    def run(self, state: WorkflowState, storage: Path) -> TestResults:
        reader = workspace_reader(state, storage)
        files = reader.inventory().files
        tests = [path for path in files if path.startswith("tests/") and Path(path).name.startswith("test") and path.endswith(".py")]
        framework = getattr(self.process, "framework", "unittest")
        if not tests and not (framework == "npm" and "package.json" in files):
            return TestResults(outcome=TestOutcome.SKIPPED,
                summary="No supported tests were found; nothing was executed.",
                recommendation="Add tests under tests/ or configure a supported test framework.")
        execution = self.process.run(reader.root)
        if execution.timed_out or execution.error:
            outcome = TestOutcome.ERROR
            summary = "Test execution did not complete within its configured bounds."
            cause = execution.error or "Test execution exceeded its wall-clock timeout."
        elif execution.exit_code == 0:
            outcome = TestOutcome.PASSED
            summary = f"The {framework} suite completed with exit code 0. Individual counts are not inferred from console text."
            cause = None
        else:
            outcome = TestOutcome.FAILED
            summary = f"The {framework} command returned a nonzero exit code; inspect the actual output."
            cause = "No tests were collected." if execution.exit_code == 5 else "A test, import, or discovery error occurred; see the output excerpt."
        return TestResults(outcome=outcome, executions=(execution,), summary=summary,
            suspected_cause=cause, recommendation=None if outcome == TestOutcome.PASSED else "Review the recorded test output before changing code or retrying.")
