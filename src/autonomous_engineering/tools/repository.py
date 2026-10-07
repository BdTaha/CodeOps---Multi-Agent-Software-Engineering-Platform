"""Read-only, bounded repository access for trusted local snapshots."""

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from pydantic import PositiveInt, TypeAdapter, ValidationError

from autonomous_engineering.domain.base import DomainModel, RepositoryFile

EXCLUDED_DIRECTORIES = frozenset({
    ".git", ".hg", ".svn", ".workspaces", "node_modules", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build", "coverage",
    ".next", ".idea", ".aws", ".ssh", ".codex",
})
SECRET_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".keystore"})
FILE_ADAPTER = TypeAdapter(RepositoryFile)


class RepositoryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class InspectionLimits(DomainModel):
    max_files: PositiveInt = 2000
    max_entries: PositiveInt = 20000
    max_depth: PositiveInt = 32
    max_file_bytes: PositiveInt = 262144
    max_total_bytes: PositiveInt = 16777216


@dataclass(frozen=True)
class Inventory:
    files: tuple[str, ...]
    excluded_entries: int


def is_link(path: Path) -> bool:
    info = path.lstat()
    # Covers Windows junctions/reparse points on Python 3.11 as well as symlinks.
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def excluded(path: Path, *, directory: bool) -> bool:
    name = path.name.casefold()
    if directory:
        return name in EXCLUDED_DIRECTORIES or name.startswith(".venv") or name.endswith(".egg-info")
    return (
        (name.startswith(".env") and name not in {".env.example", ".env.sample"})
        or path.suffix.casefold() in SECRET_SUFFIXES
        or name in {"id_rsa", "id_ed25519", ".npmrc", ".pypirc", "credentials"}
    )


class RepositoryReader:
    """Only reads regular files beneath one root; never follows links.

    These checks handle ordinary local repositories, not hostile concurrent
    filesystem replacement. An OS/container sandbox remains a later phase.
    """

    def __init__(self, root: Path, limits: InspectionLimits | None = None) -> None:
        self.limits = limits or InspectionLimits()
        try:
            if is_link(root) or not root.is_dir():
                raise RepositoryError("INVALID_REPOSITORY", "Repository root must be a regular directory.")
            self.root = root.resolve(strict=True)
        except OSError as exc:
            raise RepositoryError("REPOSITORY_NOT_FOUND", "Repository directory is missing or inaccessible.") from exc

    def inventory(self, *, omit_root: Path | None = None) -> Inventory:
        files: list[str] = []
        excluded_count = 0
        visited = 0
        stack = [(self.root, 0)]
        try:
            while stack:
                folder, depth = stack.pop()
                if depth > self.limits.max_depth:
                    raise RepositoryError("INSPECTION_LIMIT", "Repository directory depth exceeds the inspection limit.")
                entries = []
                with os.scandir(folder) as iterator:
                    for entry in iterator:
                        visited += 1
                        if visited > self.limits.max_entries:
                            raise RepositoryError("INSPECTION_LIMIT", "Repository entry count exceeds the inspection limit.")
                        entries.append(entry)
                for entry in sorted(entries, key=lambda item: item.name):
                    path = Path(entry.path)
                    info = entry.stat(follow_symlinks=False)
                    if is_link(path) or (omit_root is not None and path == omit_root):
                        excluded_count += 1
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        if excluded(path, directory=True):
                            excluded_count += 1
                        else:
                            stack.append((path, depth + 1))
                    elif stat.S_ISREG(info.st_mode) and not excluded(path, directory=False):
                        try:
                            relative = FILE_ADAPTER.validate_python(path.relative_to(self.root).as_posix())
                        except ValidationError:
                            excluded_count += 1
                            continue
                        files.append(relative)
                        if len(files) > self.limits.max_files:
                            raise RepositoryError("INSPECTION_LIMIT", "Repository file count exceeds the inspection limit.")
                    else:
                        excluded_count += 1
        except OSError as exc:
            raise RepositoryError("REPOSITORY_ACCESS", "Repository inventory could not be read.") from exc
        return Inventory(tuple(sorted(files)), excluded_count)

    def read_text(self, relative: str) -> str:
        try:
            normalized = FILE_ADAPTER.validate_python(relative)
        except ValidationError as exc:
            raise RepositoryError("INVALID_PATH", "File reference must stay inside the repository.") from exc
        path = self.root
        try:
            for index, part in enumerate(Path(normalized).parts):
                path = path / part
                if is_link(path) or excluded(path, directory=index < len(Path(normalized).parts) - 1):
                    raise RepositoryError("PATH_DENIED", "Links and excluded repository paths cannot be read.")
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(self.root) or not stat.S_ISREG(path.stat().st_mode):
                raise RepositoryError("PATH_DENIED", "Only repository regular files can be read.")
            with path.open("rb") as stream:
                data = stream.read(self.limits.max_file_bytes + 1)
            if len(data) > self.limits.max_file_bytes:
                raise RepositoryError("FILE_TOO_LARGE", "File exceeds the per-file inspection limit.")
            if b"\x00" in data:
                raise RepositoryError("NOT_TEXT", "Binary files are excluded from text inspection.")
            return data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise RepositoryError("NOT_TEXT", "Non-UTF-8 files are excluded from text inspection.") from exc
        except OSError as exc:
            raise RepositoryError("REPOSITORY_ACCESS", "Repository file is missing or inaccessible.") from exc
