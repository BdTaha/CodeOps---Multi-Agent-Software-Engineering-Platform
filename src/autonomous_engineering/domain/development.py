"""Structured proposals; these contracts never apply edits."""

from pydantic import Field, model_validator
from autonomous_engineering.domain.base import DomainModel, RepositoryFile, Summary
from autonomous_engineering.domain.results import ChangeKind


class FileEdit(DomainModel):
    path: RepositoryFile
    kind: ChangeKind
    content: str | None = Field(default=None, max_length=32000)
    summary: Summary

    @model_validator(mode="after")
    def validate_content(self) -> "FileEdit":
        if (self.kind == ChangeKind.DELETED) != (self.content is None):
            raise ValueError("deletions require null content; other edits require full text")
        if self.content is not None and "\x00" in self.content:
            raise ValueError("binary content is not supported")
        if self.content is not None:
            try:
                self.content.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError("content must be valid UTF-8 text") from exc
        return self


class DevelopmentProposal(DomainModel):
    explanation: Summary
    edits: tuple[FileEdit, ...] = Field(min_length=1, max_length=8)


