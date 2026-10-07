"""Shared validation primitives for serializable domain contracts."""

from datetime import datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, StringConstraints

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Summary = Annotated[NonBlank, StringConstraints(max_length=4000)]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


UtcTimestamp = Annotated[AwareDatetime, AfterValidator(as_utc)]


def repository_relative_path(value: str) -> str:
    """Validate a reference, not filesystem confinement or file existence."""
    normalized = value.replace("\\", "/")
    if (
        "\x00" in normalized
        or PureWindowsPath(value).drive
        or normalized.startswith("/")
        or ".." in normalized.split("/")
        or ":" in normalized
    ):
        raise ValueError("file references must be relative paths without traversal")
    path = str(PurePosixPath(normalized))
    if path == ".":
        raise ValueError("a file path is required")
    return path


RepositoryFile = Annotated[NonBlank, AfterValidator(repository_relative_path)]


class DomainModel(BaseModel):
    """Reject misspelled fields and validate new instances at every boundary.

    Frozen models and tuple collections prevent accidental in-place updates.
    Use validation, never model_construct or unvalidated model_copy updates,
    when accepting external data.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
