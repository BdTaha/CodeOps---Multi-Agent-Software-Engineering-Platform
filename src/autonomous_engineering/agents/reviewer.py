"""Read-only review of actual snapshot changes and passing test evidence."""

from pathlib import Path
import hashlib
from typing import Protocol

from pydantic import ValidationError

from autonomous_engineering.agents.developer import approval_identity, workspace_reader
from autonomous_engineering.domain.base import DomainModel
from autonomous_engineering.domain.results import ImplementationPlan, ReviewResults, TestOutcome, TestResults
from autonomous_engineering.domain.tasks import TaskRequest
from autonomous_engineering.tools.repository import RepositoryError
from autonomous_engineering.workflows.state import WorkflowState


class ReviewContext(DomainModel):
    task: TaskRequest
    plan: ImplementationPlan
    diff: str
    files: dict[str, str | None]
    tests: TestResults
    limitations: tuple[str, ...]


class ReviewProvider(Protocol):
    def generate(self, context: ReviewContext) -> ReviewResults: ...


class Reviewer:
    def __init__(self, provider: ReviewProvider):
        self.provider = provider

    def review(self, state: WorkflowState, storage: Path) -> ReviewResults:
        if state.development is None or state.plan is None or state.tests is None or state.tests.outcome != TestOutcome.PASSED:
            raise RepositoryError("REVIEW_EVIDENCE_REQUIRED", "Review requires actual development and passing test execution evidence.")
        identity = approval_identity(state, storage)
        reader = workspace_reader(state, storage)
        inventory = reader.inventory().files
        paths = list(dict.fromkeys(change.path for change in state.changes))
        tests = [path for path in inventory if path.startswith("tests/") and Path(path).name.startswith("test") and path.endswith(".py")]
        if len(paths) > 8 or len(tests) > 20 or len(state.development.diff) > 48000:
            raise RepositoryError("REVIEW_CONTEXT_LIMIT", "Review evidence exceeds the bounded context; narrow the task or test suite.")
        files = {path: reader.read_text(path) if path in inventory else None for path in dict.fromkeys([*paths, *tests])}
        if set(state.development.content_hashes) != set(paths):
            raise RepositoryError("REVIEW_EVIDENCE_REQUIRED", "Development lacks exact resulting-file evidence; develop a fresh snapshot before review.")
        for path in paths:
            content = files[path]
            actual = hashlib.sha256(content.encode("utf-8")).hexdigest() if content is not None else None
            if actual != state.development.content_hashes[path]:
                raise RepositoryError("STALE_REVIEW", "A developed file changed after implementation; its diff and test evidence cannot be approved.")
        if any(text is not None and len(text) > 32000 for text in files.values()) or sum(len(text or "") for text in files.values()) > 24000:
            raise RepositoryError("REVIEW_CONTEXT_LIMIT", "Review source exceeds the full-file context budget; no truncated approval is allowed.")
        context = ReviewContext(task=state.task.request, plan=state.plan, diff=state.development.diff,
            files=files, tests=state.tests, limitations=(
                "Only changed files and the existing Python test suite are supplied; other source files were not reviewed.",
                "Passing tests do not establish complete feature coverage; check the actual test source against the task.",
                "This is a local model review, not a guarantee of correctness or security.",))
        try:
            result = ReviewResults.model_validate(self.provider.generate(context))
        except ValidationError as exc:
            raise RepositoryError("INVALID_REVIEW", "Provider returned an invalid structured review decision.") from exc
        if len(result.findings) > 6:
            raise RepositoryError("INVALID_REVIEW", "Review contains too many findings.")
        for finding in result.findings:
            if finding.file is None or finding.file not in files:
                raise RepositoryError("INVALID_REVIEW", "Review finding references a file outside its supplied evidence.")
            if finding.line is not None:
                content = files.get(finding.file)
                if content is None or finding.line > len(content.splitlines()):
                    raise RepositoryError("INVALID_REVIEW", "Review finding references a nonexistent source line.")
            content = files[finding.file]
            if content is not None and (finding.line is None or finding.evidence is None
                    or finding.evidence not in content.splitlines()[finding.line - 1]):
                raise RepositoryError("INVALID_REVIEW", "Review findings must quote an exact excerpt from their referenced source line.")
            if content is None and (finding.evidence is None or finding.evidence not in state.development.diff):
                raise RepositoryError("INVALID_REVIEW", "Deleted-file findings require an exact excerpt from the actual diff.")
        if approval_identity(state, storage) != identity:
            raise RepositoryError("STALE_REVIEW", "Snapshot changed during review; the decision was discarded.")
        return result
