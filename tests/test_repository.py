import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from autonomous_engineering.infrastructure.workspaces import WorkspacePreparer
from autonomous_engineering.tools.repository import InspectionLimits, RepositoryError, RepositoryReader


def write(root: Path, name: str, content: str) -> None:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       check=True, capture_output=True, text=True)
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.fixture
def repo(tmp_path) -> Path:
    source = tmp_path / "repo"
    source.mkdir()
    write(source, "src/auth.py", "def login(): return True\n")
    return source


@pytest.mark.parametrize("path", ["../secret.txt", "/etc/passwd", "C:\\secret", ".", "src/../../secret", "src\x00/file"])
def test_reader_rejects_escaping_paths(repo, path) -> None:
    with pytest.raises(RepositoryError):
        RepositoryReader(repo).read_text(path)


def test_reader_normalizes_relative_windows_paths(repo) -> None:
    assert "login" in RepositoryReader(repo).read_text("src\\auth.py")


@pytest.mark.parametrize("name", [".env", ".env.production", "secret.pem", ".npmrc", "id_rsa"])
def test_reader_denies_common_credentials(repo, name) -> None:
    write(repo, name, "DO_NOT_READ")
    reader = RepositoryReader(repo)
    assert name not in reader.inventory().files
    with pytest.raises(RepositoryError, match="excluded"):
        reader.read_text(name)


def test_reader_rejects_directory_and_missing_file(repo) -> None:
    for path in ("src", "missing.py"):
        with pytest.raises(RepositoryError):
            RepositoryReader(repo).read_text(path)


def test_snapshot_is_isolated_and_omits_generated_private_and_binary_files(repo, tmp_path) -> None:
    write(repo, ".env", "SECRET")
    write(repo, ".env.example", "SETTING=example")
    write(repo, ".git/config", "SECRET")
    write(repo, ".venv-backup/site.py", "generated")
    write(repo, "node_modules/dependency/index.js", "generated")
    write(repo, "large.txt", "x" * 100)
    (repo / "image.bin").write_bytes(b"\x00\x01")
    (repo / "legacy.txt").write_bytes(b"\xff")
    prepared = WorkspacePreparer(tmp_path / "workspaces", InspectionLimits(max_file_bytes=80)).prepare(repo, uuid4())
    assert RepositoryReader(prepared.root).inventory().files == (".env.example", "src/auth.py")
    assert not (prepared.root / ".git").exists()
    assert "3 oversized" in prepared.notes[0]
    write(repo, "src/auth.py", "changed source")
    assert "login" in RepositoryReader(prepared.root).read_text("src/auth.py")
    write(prepared.root, "src/auth.py", "changed snapshot")
    assert (repo / "src/auth.py").read_text() == "changed source"


def test_snapshot_excludes_managed_storage_inside_source(repo) -> None:
    storage = repo / "custom-storage"
    write(storage, "old/file.py", "generated")
    prepared = WorkspacePreparer(storage).prepare(repo, uuid4())
    assert RepositoryReader(prepared.root).inventory().files == ("src/auth.py",)


def test_existing_snapshot_is_never_overwritten(repo, tmp_path) -> None:
    preparer = WorkspacePreparer(tmp_path / "workspaces")
    run_id = uuid4()
    prepared = preparer.prepare(repo, run_id)
    with pytest.raises(RepositoryError, match="already exists"):
        preparer.prepare(repo, run_id)
    assert "login" in (prepared.root / "src/auth.py").read_text()


@pytest.mark.parametrize("limits", [
    InspectionLimits(max_files=1), InspectionLimits(max_entries=1),
    InspectionLimits(max_total_bytes=5), InspectionLimits(max_depth=1),
])
def test_snapshot_hard_limits_fail_before_destination_creation(repo, tmp_path, limits) -> None:
    write(repo, "deep/nested/file.py", "second file")
    storage = tmp_path / "workspaces"
    with pytest.raises(RepositoryError) as error:
        WorkspacePreparer(storage, limits).prepare(repo, uuid4())
    assert error.value.code == "INSPECTION_LIMIT"
    assert not storage.exists()


def test_reader_per_file_byte_limit(repo) -> None:
    with pytest.raises(RepositoryError) as error:
        RepositoryReader(repo, InspectionLimits(max_file_bytes=3)).read_text("src/auth.py")
    assert error.value.code == "FILE_TOO_LARGE"


def test_junction_or_symlink_escape_is_neither_listed_nor_read(repo, tmp_path) -> None:
    outside = tmp_path / "outside"
    write(outside, "secret.py", "SECRET")
    directory_link(repo / "escape", outside)
    reader = RepositoryReader(repo)
    assert reader.inventory().files == ("src/auth.py",)
    with pytest.raises(RepositoryError, match="Links"):
        reader.read_text("escape/secret.py")
    prepared = WorkspacePreparer(tmp_path / "workspaces").prepare(repo, uuid4())
    assert not (prepared.root / "escape").exists()


def test_workspace_storage_cannot_follow_a_link(repo, tmp_path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "linked-storage"
    directory_link(link, outside)
    with pytest.raises(RepositoryError) as error:
        WorkspacePreparer(link / "child").prepare(repo, uuid4())
    assert error.value.code == "WORKSPACE_DENIED"
    assert list(outside.iterdir()) == []


def test_linked_repository_root_is_rejected(repo, tmp_path) -> None:
    link = tmp_path / "linked-source"
    directory_link(link, repo)
    with pytest.raises(RepositoryError):
        RepositoryReader(link)


def test_empty_directory_snapshot_is_valid(tmp_path) -> None:
    source = tmp_path / "empty"
    source.mkdir()
    prepared = WorkspacePreparer(tmp_path / "workspaces").prepare(source, uuid4())
    assert RepositoryReader(prepared.root).inventory().files == ()
