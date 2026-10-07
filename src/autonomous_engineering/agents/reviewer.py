"""Read-only review of actual snapshot changes and passing test evidence."""

from pathlib import Path
import hashlib
from html.parser import HTMLParser
import re
from textwrap import dedent
from typing import Protocol

from pydantic import Field, ValidationError

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
    source_facts: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    developer_repair_feedback: str | None = None
    review_validation_feedback: str | None = None


def html_source_facts(files):
    class Tags(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ends = []
        def handle_endtag(self, tag):
            if tag in {'html','body','head'}:
                self.ends.append(f'Explicit </{tag}> end tag exists at line {self.getpos()[0]}.')
    facts = {}
    for path, content in files.items():
        if content is not None and Path(path).suffix.lower() in {'.html','.htm'}:
            parser = Tags()
            parser.feed(content)
            facts[path] = tuple(parser.ends)
    return facts


def recommendation_is_unchanged(recommendation: str, content: str) -> bool:
    """Detect a complete suggested replacement identical to the current file.

    This checks whether a repair is actionable, not whether the file is correct.
    Preserve internal whitespace: changing indentation or string literals can
    change behavior. Removal/movement suggestions legitimately quote existing code.
    """
    if not re.search(r'\b(add|insert|replace|update|use|set)\b', recommendation, re.I):
        return False
    if re.search(r'\b(remove|delete|move|relocate|reorder)\b', recommendation, re.I):
        return False
    blocks = re.findall(r'```[^\n]*\n(.*?)```', recommendation, re.S)
    if not blocks:
        blocks = [recommendation]
        # Plain prose followed by a code paragraph is common with local models.
        blocks.extend(recommendation.split('\n\n')[1:])
        first, separator, rest = recommendation.partition('\n')
        if ': ' in first:
            blocks.append(first.rsplit(': ', 1)[1] + separator + rest)
    source = content.replace('\r\n', '\n')
    for block in blocks:
        snippet = dedent(block.replace('\r\n', '\n')).strip('\n ')
        if len([line for line in snippet.splitlines() if line.strip() not in {'', '{', '}'}]) >= 2 and snippet == source.strip('\n '):
            return True
    return False


def unchanged_recommendation_path(finding, files: dict[str, str | None]) -> str | None:
    candidates = [finding.file]
    # A finding can cite HTML while explicitly recommending a CSS file edit.
    # Resolve only unambiguous filenames named in the recommendation; do not
    # equate a snippet elsewhere in the repository with the proposed repair.
    for path in files:
        name = Path(path).name
        if sum(Path(other).name == name for other in files) == 1 and re.search(
                rf'(?<![\w/\\]){re.escape(name)}(?![\w/\\])', finding.recommended_fix):
            candidates.append(path)
    for path in dict.fromkeys(candidates):
        content = files.get(path)
        if content is not None and recommendation_is_unchanged(finding.recommended_fix, content):
            return path
    return None


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
            files=files, tests=state.tests, source_facts=html_source_facts(files),
            developer_repair_feedback=state.development.repair_note, limitations=(
                "Only changed files and the existing Python test suite are supplied; other source files were not reviewed.",
                "Passing tests do not establish complete feature coverage; check the actual test source against the task.",
                "This is a local model review, not a guarantee of correctness or security.",))
        usage = []
        for attempt in range(2):
            result = None
            try:
                raw = self.provider.generate(context)
                measured = getattr(self.provider, 'last_usage', None)
                if measured:
                    usage.append(dict(measured))
                # A new model decision must never legitimize changed evidence.
                if approval_identity(state, storage) != identity:
                    raise RepositoryError("STALE_REVIEW", "Snapshot changed during review; the decision was discarded.")
                try:
                    result = ReviewResults.model_validate(raw)
                except ValidationError as exc:
                    raise RepositoryError("INVALID_REVIEW", "Provider returned an invalid structured review decision.") from exc
                self._validate_result(result, context)
                if attempt:
                    result = result.model_copy(update={'summary': ('After evidence recheck: ' + result.summary)[:4000]})
                return result
            except RepositoryError as exc:
                if attempt or exc.code not in {'INVALID_REVIEW', 'REVIEW_CONTRADICTION'}:
                    raise
                context = context.model_copy(update={'review_validation_feedback':
                    f'The previous decision failed evidence validation: {exc}\n'
                    + ('Previous decision (untrusted model output): ' + result.model_dump_json()[:6000] if result else 'The previous decision violated the structured review contract.')})
            finally:
                if usage and hasattr(self.provider, 'last_usage'):
                    total = {'model': usage[-1].get('model')}
                    for field in ('input_tokens', 'output_tokens'):
                        if all(type(item.get(field)) is int for item in usage):
                            total[field] = sum(item[field] for item in usage)
                    self.provider.last_usage = total
        raise AssertionError('bounded review must return or raise')

    @staticmethod
    def _validate_result(result: ReviewResults, context: ReviewContext) -> None:
        files = context.files
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
            unchanged_path = unchanged_recommendation_path(finding, files)
            if unchanged_path is not None:
                raise RepositoryError('REVIEW_CONTRADICTION',
                    f'The recommended code for {unchanged_path} already exists verbatim as the entire current file. Replacing this file with that code would make no change. Recheck the actual defect and explain an actionable change or its required location; existing CSS declarations alone do not prove that a stylesheet loads or wins the cascade.')
            if content is not None and Path(finding.file).suffix.lower() in {'.html','.htm'}:
                claim = finding.description.lower()
                if re.search(r'\b(missing|absent|lacks|without)\b',claim):
                    tags = re.findall(r'</(html|head|body)\s*>',claim)
                    for tag in tags:
                        if any(f'Explicit </{tag}> end tag exists' in fact for fact in context.source_facts.get(finding.file,())):
                            raise RepositoryError('REVIEW_CONTRADICTION',
                                f'Reviewer claims </{tag}> is missing from {finding.file}, but the source parser confirms it exists. The review is unreliable; inspect the code or use a different reviewer model.')
            if content is not None and (finding.line is None or finding.evidence is None
                    or finding.evidence not in content.splitlines()[finding.line - 1]):
                raise RepositoryError("INVALID_REVIEW", "Review findings must quote an exact excerpt from their referenced source line.")
            if content is None and (finding.evidence is None or finding.evidence not in context.diff):
                raise RepositoryError("INVALID_REVIEW", "Deleted-file findings require an exact excerpt from the actual diff.")
