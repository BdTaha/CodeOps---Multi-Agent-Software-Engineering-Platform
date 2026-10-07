"""Read-only planning with bounded evidence and an injected generation boundary."""

from typing import Protocol
from pathlib import PurePosixPath

from pydantic import Field, ValidationError

from autonomous_engineering.domain.base import DomainModel, RepositoryFile, Summary
from autonomous_engineering.domain.results import ImplementationPlan, RepositoryAnalysis
from autonomous_engineering.domain.tasks import TaskRequest
from autonomous_engineering.tools.repository import RepositoryReader


class PlanningError(ValueError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class SourceExcerpt(DomainModel):
    path: RepositoryFile
    content: str = Field(max_length=6000)
    truncated: bool


class PlanningContext(DomainModel):
    task: TaskRequest
    analysis: RepositoryAnalysis
    excerpts: tuple[SourceExcerpt, ...] = Field(max_length=12)
    limitations: tuple[Summary, ...] = ()


class PlanProvider(Protocol):
    def generate(self, context: PlanningContext) -> ImplementationPlan:
        """Generate a draft; implementations must not execute repository code."""
        ...


class Planner:
    def __init__(self, provider: PlanProvider) -> None:
        self.provider = provider

    def plan(
        self, reader: RepositoryReader, task: TaskRequest, analysis: RepositoryAnalysis,
    ) -> ImplementationPlan:
        analysis = RepositoryAnalysis.model_validate(analysis)
        paths = tuple(dict.fromkeys((*analysis.relevant_files, *analysis.important_files)))
        # Keep long prose from exhausting the budget before source is inspected.
        paths = tuple(sorted(paths, key=lambda path: PurePosixPath(path).suffix.lower() in {".md", ".rst", ".txt"}))
        excerpts: list[SourceExcerpt] = []
        remaining = 12000
        for path in paths[:12]:
            if not remaining:
                break
            content = reader.read_text(path)
            count = min(6000, remaining)
            excerpts.append(SourceExcerpt(path=path, content=content[:count],
                                          truncated=len(content) > count))
            remaining -= len(excerpts[-1].content)
        limitations = ["Planning is a draft based on static inspection; no tests or code changes have run."]
        if len(excerpts) < len(paths):
            limitations.append("The context budget omitted some candidate files.")
        if any(excerpt.truncated for excerpt in excerpts):
            limitations.append("Some source excerpts are truncated; their omitted content is unknown.")
        context = PlanningContext(task=task, analysis=analysis, excerpts=tuple(excerpts),
                                  limitations=tuple(limitations))
        known_files = frozenset(reader.inventory().files)
        try:
            # Revalidate even typed provider returns: model output is untrusted data.
            result = ImplementationPlan.model_validate(self.provider.generate(context))
            values = result.model_dump()
            adjusted = False
            steps = []
            for step in result.steps:
                files = []
                for path in step.files:
                    matches = sorted(candidate for candidate in known_files if candidate.endswith("/" + path))
                    resolved = matches[0] if path not in known_files and len(matches) == 1 else path
                    adjusted |= resolved != path
                    files.append(resolved)
                steps.append(type(step)(description=step.description, files=tuple(dict.fromkeys(files))))
            unique_steps = tuple(dict.fromkeys(steps))
            if len(unique_steps) < len(steps):
                limitations.append("Repeated identical model steps were removed from this draft.")
            if adjusted:
                limitations.append("Unambiguous shortened file references were resolved to their existing snapshot paths; descriptions remain model-generated.")
            proposed = sorted({path for step in unique_steps for path in step.files if path not in known_files})
            if proposed:
                limitations.append(f"{len(proposed)} proposed paths are not present in the snapshot and require review (list limited to 3500 characters): " + ", ".join(proposed)[:3500])
            values["steps"] = unique_steps
            # Evidence provenance belongs to the reader, never the model.
            values["context_files"] = tuple(excerpt.path for excerpt in excerpts)
            values["limitations"] = tuple(dict.fromkeys((*limitations, *analysis.limitations)))
            return ImplementationPlan.model_validate(values)
        except ValidationError as exc:
            raise PlanningError("INVALID_PLAN", "The provider returned an invalid implementation plan.") from exc
