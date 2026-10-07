"""Prepare bounded text snapshots without executing repository code."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from autonomous_engineering.tools.repository import (
    InspectionLimits,
    RepositoryError,
    RepositoryReader,
    is_link,
)


@dataclass(frozen=True)
class PreparedWorkspace:
    root: Path
    notes: tuple[str, ...]


class WorkspacePreparer:
    def __init__(self, root: Path, limits: InspectionLimits | None = None) -> None:
        self.root = root.absolute()
        self.limits = limits or InspectionLimits()

    def prepare(self, source: Path, run_id: UUID) -> PreparedWorkspace:
        reader = RepositoryReader(source, self.limits)
        # Reject existing link components before any destination writes.
        try:
            for component in (*reversed(self.root.parents), self.root):
                if component.exists() and is_link(component):
                    raise RepositoryError("WORKSPACE_DENIED", "Workspace storage cannot traverse links.")
            destination_root = self.root.resolve()
            if reader.root == destination_root or reader.root.is_relative_to(destination_root):
                raise RepositoryError("WORKSPACE_DENIED", "Source cannot be a managed workspace directory.")
            destination = destination_root / str(run_id)
            if destination.exists():
                raise RepositoryError("WORKSPACE_EXISTS", "A workspace already exists for this run.")
            inventory = reader.inventory(omit_root=destination_root)
            contents: list[tuple[str, str]] = []
            total = 0
            skipped = 0
            for relative in inventory.files:
                try:
                    text = reader.read_text(relative)
                except RepositoryError as exc:
                    if exc.code in {"FILE_TOO_LARGE", "NOT_TEXT"}:
                        skipped += 1
                        continue
                    raise
                total += len(text.encode("utf-8"))
                if total > self.limits.max_total_bytes:
                    raise RepositoryError("INSPECTION_LIMIT", "Repository text exceeds the total inspection limit.")
                contents.append((relative, text))
            destination.mkdir(parents=True, exist_ok=False)
            for relative, text in contents:
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8", newline="")
        except OSError as exc:
            raise RepositoryError("WORKSPACE_ACCESS", "Workspace snapshot could not be created.") from exc
        return PreparedWorkspace(destination, (
            f"Snapshot excluded {inventory.excluded_entries} filtered entries/directories and {skipped} oversized, binary, or non-UTF-8 files.",
            "Snapshot includes eligible local text, including uncommitted files; Git metadata and excluded-directory contents are not inspected.",
        ))
