"""Confined text edits, whole-proposal validation and ordinary I/O rollback."""

import difflib
from pathlib import Path
from autonomous_engineering.domain.development import DevelopmentProposal, FileEdit
from autonomous_engineering.domain.results import ChangeKind, CodeChange
from autonomous_engineering.tools.repository import RepositoryReader, RepositoryError, excluded, is_link


def checked_target(reader: RepositoryReader, relative: str) -> Path:
    target = reader.root
    parts = Path(relative).parts
    for index, part in enumerate(parts):
        # Reject Windows aliases/device names on all platforms, including trailing
        # dots/spaces which Windows normalizes to another path.
        base = part.split(".")[0].upper()
        if (any(ord(c) < 32 or c in '<>"|?*' for c in part) or part.endswith((".", " "))
            or base in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}):
            raise RepositoryError("PATH_DENIED", "Platform reserved paths cannot be edited.")
        target /= part
        if excluded(target, directory=index < len(parts)-1) or (target.exists() and is_link(target)) or target.is_symlink():
            raise RepositoryError("PATH_DENIED", "Excluded paths and links cannot be edited.")
    if not target.resolve().is_relative_to(reader.root):
        raise RepositoryError("PATH_DENIED", "Edits must stay inside the managed snapshot.")
    return target


def review_diff(edit: FileEdit, before: str | None) -> str:
    lines = difflib.unified_diff(
        (before or "").splitlines(keepends=True), (edit.content or "").splitlines(keepends=True),
        fromfile="/dev/null" if before is None else "a/" + edit.path,
        tofile="/dev/null" if edit.content is None else "b/" + edit.path,
    )
    diff = "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines)
    return diff or f"{edit.kind.value}: {edit.path} (empty file)\n"


def apply_edits(reader: RepositoryReader, proposal: DevelopmentProposal, files: dict[str, str | None]) -> tuple[str, tuple[CodeChange, ...]]:
    staged: list[tuple[FileEdit, Path, str | None]] = []
    seen: set[str] = set()
    for edit in proposal.edits:
        if edit.path not in files or edit.path.casefold() in seen:
            raise RepositoryError("DEVELOPMENT_SCOPE", "Generated edits must use unique paths from the approved plan.")
        seen.add(edit.path.casefold())
        target = checked_target(reader, edit.path)
        before = files[edit.path]
        if (edit.kind == ChangeKind.CREATED) != (before is None):
            expected = 'created' if before is None else 'modified or deleted'
            raise RepositoryError("INVALID_EDIT", f"Generated edit kind for {edit.path} does not match file existence; expected {expected}.")
        if before == edit.content:
            # A model may repeat an existing file beside substantive edits.
            # Its scope, kind, and path were still validated above; omit it from
            # both filesystem writes and the reported diff.
            continue
        staged.append((edit, target, before))
    if not staged:
        raise RepositoryError("INVALID_EDIT", "Generated edits do not change any file.")
    if sum(len((edit.content or "").encode("utf-8")) for edit, _, _ in staged) > 128000:
        raise RepositoryError("DEVELOPMENT_OUTPUT_LIMIT", "Generated changes exceed the output budget.")
    diff = "".join(review_diff(edit, before) for edit, _, before in staged)
    applied: list[tuple[Path, str | None]] = []
    try:
        for edit, target, before in staged:
            target.parent.mkdir(parents=True, exist_ok=True)
            applied.append((target, before))
            if edit.content is None:
                target.unlink()
            else:
                target.write_text(edit.content, encoding="utf-8", newline="")
    except OSError as exc:
        # Best-effort rollback. Fail visibly if even recovery is unavailable.
        try:
            for target, before in reversed(applied):
                if before is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_text(before, encoding="utf-8", newline="")
        except OSError as recovery:
            raise RepositoryError("WORKSPACE_RECOVERY_FAILED", "Snapshot writes and rollback failed; inspect the retained workspace.") from recovery
        raise RepositoryError("WORKSPACE_WRITE_FAILED", "Snapshot writes failed; file contents were rolled back.") from exc
    return diff, tuple(CodeChange(path=e.path, kind=e.kind, summary=e.summary) for e, _, _ in staged)
