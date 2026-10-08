"""Bounded read-only observations for product planning; no raw source in prompts."""
from pathlib import Path, PurePosixPath

from autonomous_engineering.agents.repository_analyzer import RepositoryAnalyzer, IMPORTANT_NAMES
from autonomous_engineering.domain.product_planning import PlanningBasis
from autonomous_engineering.tools.repository import RepositoryReader, RepositoryError, InspectionLimits, Inventory

MAX_FILES = 40
MAX_FILE_BYTES = 65536
MAX_TOTAL_BYTES = 262144


def planning_context(project: dict, goal: str) -> PlanningBasis:
    if not project.get('path'):
        return PlanningBasis(mode='goal_only', reason='Repository is not registered.')
    try:
        reader = RepositoryReader(Path(project['path']), InspectionLimits(max_file_bytes=MAX_FILE_BYTES))
    except RepositoryError as exc:
        if exc.code not in {'REPOSITORY_NOT_FOUND', 'INVALID_REPOSITORY'}:
            raise
        return PlanningBasis(mode='goal_only', reason=f'{exc.code}: Repository is missing, inaccessible, or unsupported.')
    inventory = reader.inventory()  # Inventory/access/limit bugs are visible failures, not fallback.
    candidates = [path for path in inventory.files if len(path) <= 200 and not any(
        part.casefold().startswith('.env') or any(word in part.casefold() for word in ('secret', 'credential', 'token', 'password'))
        for part in PurePosixPath(path).parts)]
    tokens = set(goal.casefold().split())
    def rank(path):
        name = PurePosixPath(path).name.casefold()
        manifest = name in IMPORTANT_NAMES or name.startswith('requirements') or name in {'build.gradle', 'build.gradle.kts'}
        relevant = any(token in path.casefold() for token in tokens if len(token) > 3)
        return (not manifest, not relevant, path)
    texts, total, skipped = {}, 0, 0
    for path in sorted(candidates, key=rank):
        if len(texts) >= MAX_FILES:
            break
        try:
            content = reader.read_text(path)
        except RepositoryError as exc:
            if exc.code not in {'NOT_TEXT', 'FILE_TOO_LARGE'}:
                raise
            skipped += 1
            continue
        size = len(content.encode('utf-8'))
        if total + size > MAX_TOTAL_BYTES:
            skipped += 1
            continue
        total += size
        texts[path] = content
    class ObservedReader:
        limits = InspectionLimits(max_files=MAX_FILES, max_file_bytes=MAX_FILE_BYTES, max_total_bytes=MAX_TOTAL_BYTES)
        def inventory(self):
            return Inventory(tuple(texts), inventory.excluded_entries + skipped)
        def read_text(self, path):
            return texts[path]
    analysis = RepositoryAnalyzer().analyze(ObservedReader(), goal)
    return PlanningBasis(mode='repository_grounded', analysis=analysis, inspected_files=tuple(texts), limitations=(
        'Read-only sample: at most 40 UTF-8 files, 64 KiB per file and 256 KiB total; inventory is bounded to 2000 files/20000 entries.',
        'Only observed paths, layout, language and declared dependency names reach the model; raw source and manifest values are omitted.',
        'Secrets/configuration candidates, links, VCS internals, binaries, oversized files and build/dependency directories are excluded.',
        'Layout and manifest observations do not verify runtime capabilities, storage behavior or test correctness.',
    ))
