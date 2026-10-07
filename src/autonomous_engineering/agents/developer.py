"""Bounded development of an explicitly approved plan in a managed snapshot.

No generated code or commands are executed. The caller owns approval collection;
the model cannot supply an approval or choose a workspace.
"""

import hashlib
import json
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from autonomous_engineering.domain.base import DomainModel, utc_now
from autonomous_engineering.domain.results import ImplementationPlan, DevelopmentArtifact, TestResults, ReviewResults
from autonomous_engineering.domain.tasks import TaskRequest
from autonomous_engineering.tools.repository import RepositoryError, RepositoryReader, is_link
from autonomous_engineering.workflows.state import WorkflowState
from autonomous_engineering.domain.development import DevelopmentProposal
from autonomous_engineering.tools.workspace_changes import checked_target, apply_edits


class DevelopmentContext(DomainModel):
    task: TaskRequest
    plan: ImplementationPlan
    files: dict[str, str | None]
    tests: TestResults | None = None
    review: ReviewResults | None = None
    attempt: int = 1


class DevelopmentProvider(Protocol):
    def generate(self, context: DevelopmentContext) -> DevelopmentProposal: ...


def workspace_reader(state: WorkflowState, storage: Path) -> RepositoryReader:
    if not state.workspace_path:
        raise RepositoryError("WORKSPACE_DENIED", "Development requires a managed snapshot.")
    root = Path(state.workspace_path).absolute()
    for component in (*reversed(root.parents), root):
        if component.exists() and is_link(component):
            raise RepositoryError("WORKSPACE_DENIED", "Workspace paths cannot traverse links.")
    if root.resolve() != storage.resolve() / str(state.run_id):
        raise RepositoryError("WORKSPACE_DENIED", "Workspace identity does not match this run.")
    return RepositoryReader(root)


def approval_identity(state: WorkflowState, storage: Path) -> str:
    if state.plan is None:
        raise RepositoryError("PLAN_REQUIRED", "A plan is required before approval.")
    reader = workspace_reader(state, storage)
    digest = hashlib.sha256()
    identity = {"task": state.task.model_dump(mode="json"), "run_id": str(state.run_id),
                "workspace": str(reader.root), "plan": state.plan.model_dump(mode="json")}
    digest.update(json.dumps(identity, sort_keys=True).encode())
    total = 0
    for name in reader.inventory().files:
        content = reader.read_text(name).encode("utf-8")
        total += len(content)
        if total > reader.limits.max_total_bytes:
            raise RepositoryError("INSPECTION_LIMIT", "Approval snapshot exceeds the text limit.")
        digest.update(json.dumps([name, hashlib.sha256(content).hexdigest()]).encode())
    return digest.hexdigest()


class Developer:
    def __init__(self, provider: DevelopmentProvider, write_guard=None):
        self.provider = provider
        self.write_guard = write_guard

    def develop(self, state: WorkflowState, storage: Path, approved_id: str) -> DevelopmentArtifact:
        approved_at = utc_now()
        if approval_identity(state, storage) != approved_id:
            raise RepositoryError("STALE_APPROVAL", "The plan or snapshot changed; review and approve it again.")
        reader = workspace_reader(state, storage)
        assert state.plan is not None
        paths = tuple(dict.fromkeys(path for step in state.plan.steps for path in step.files))
        if not paths or len(paths) > 8 or len({p.casefold() for p in paths}) != len(paths):
            raise RepositoryError("DEVELOPMENT_SCOPE", "Approve a plan with 1–8 distinct file paths before development.")
        files: dict[str, str | None] = {}
        for path in paths:
            target = checked_target(reader, path)
            files[path] = reader.read_text(path) if target.exists() else None
        # Full files only: never silently replace a file from a truncated excerpt.
        if any(text is not None and len(text) > 32000 for text in files.values()) or sum(len(text or "") for text in files.values()) > 24000:
            raise RepositoryError("DEVELOPMENT_CONTEXT_LIMIT", "Approved files exceed the full-file context budget; narrow the plan.")
        try:
            proposal = DevelopmentProposal.model_validate(self.provider.generate(DevelopmentContext(task=state.task.request, plan=state.plan, files=files,
                tests=state.tests, review=state.review, attempt=state.development_attempts + 1)))
        except ValidationError as exc:
            raise RepositoryError("INVALID_DEVELOPMENT", "Provider returned invalid structured file edits.") from exc
        if approval_identity(state, storage) != approved_id:
            raise RepositoryError("STALE_APPROVAL", "Snapshot changed during generation; no generated edits were applied.")
        if self.write_guard is not None:
            self.write_guard()
        diff, changes = apply_edits(reader, proposal, files)
        content_hashes = {change.path: hashlib.sha256(reader.read_text(change.path).encode("utf-8")).hexdigest()
                          if change.kind != "deleted" else None for change in changes}
        return DevelopmentArtifact(approval_id=approved_id, approved_at=approved_at, explanation=proposal.explanation, diff=diff,
            changes=changes, content_hashes=content_hashes, original_files=files)
