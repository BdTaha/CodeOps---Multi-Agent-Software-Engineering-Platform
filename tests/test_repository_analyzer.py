import pytest

from autonomous_engineering.agents.repository_analyzer import RepositoryAnalyzer
from autonomous_engineering.domain.results import RepositoryAnalysis
from autonomous_engineering.infrastructure.workspaces import WorkspacePreparer
from autonomous_engineering.tools.repository import RepositoryReader
from uuid import uuid4


def write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def analyze(root, request="Inspect repository"):
    return RepositoryAnalyzer().analyze(RepositoryReader(root), request)


def test_python_manifest_layout_and_request_relevance(tmp_path) -> None:
    write(tmp_path, "pyproject.toml", '[project]\ndependencies=["fastapi>=0.115", "requests[socks]"]\n[project.optional-dependencies]\ndev=["pytest>=8"]\n')
    write(tmp_path, "src/auth.py", "def login(): return True\n")
    write(tmp_path, "src/unrelated.py", "def calculate(): return 1\n")
    write(tmp_path, "tests/test_auth.py", "def test_login(): pass\n")
    result = analyze(tmp_path, "Fix auth login")
    assert result.languages == ("Python",)
    assert result.frameworks == ("FastAPI",)
    assert result.dependencies == ("python:fastapi", "python:pytest", "python:requests")
    assert result.top_level_directories == ("src", "tests")
    assert result.inspected_file_count == 4
    assert "src/auth.py" in result.relevant_files
    assert "src/unrelated.py" not in result.relevant_files
    assert "runtime architecture has not been verified" in result.architecture_summary
    assert RepositoryAnalysis.model_validate_json(result.model_dump_json()) == result


def test_node_monorepo_manifest_and_scoped_dependency(tmp_path) -> None:
    write(tmp_path, "apps/web/package.json", '{"dependencies":{"react":"^19", "@nestjs/core":"^11"},"devDependencies":{"typescript":"^5"}}')
    write(tmp_path, "apps/web/index.tsx", "export const App = () => null;")
    result = analyze(tmp_path)
    assert result.languages == ("TypeScript",)
    assert result.frameworks == ("NestJS", "React")
    assert result.dependencies == ("node:@nestjs/core", "node:react", "node:typescript")
    assert "apps/web/package.json" in result.important_files


@pytest.mark.parametrize("name,text", [
    ("pyproject.toml", "broken = ["),
    ("pyproject.toml", '[project]\ndependencies="fastapi"'),
    ("package.json", "[]"),
    ("package.json", '{"dependencies":[]}'),
    pytest.param("package.json", '{"dependencies":' + '[' * 2000 + '0' + ']' * 2000 + '}',
                 id="deep-invalid-dependency-section"),
    ("requirements.txt", "not a valid requirement !!!!!"),
])
def test_invalid_manifests_produce_limits_without_fabricated_dependencies(tmp_path, name, text) -> None:
    write(tmp_path, name, text)
    result = analyze(tmp_path)
    assert result.dependencies == ()
    assert any("Malformed" in note for note in result.limitations)


def test_requirements_urls_do_not_leak_credentials_or_execute_includes(tmp_path) -> None:
    write(tmp_path, "requirements.txt", "fastapi>=0.115 # comment\n-r ../secret.txt\ncustom @ https://TOKEN@example.com/custom.whl\n")
    result = analyze(tmp_path)
    assert result.dependencies == ("python:custom", "python:fastapi")
    assert "TOKEN" not in result.model_dump_json()
    assert any("not followed" in note for note in result.limitations)


def test_basic_poetry_metadata_and_dynamic_dependency_disclosure(tmp_path) -> None:
    write(tmp_path, "pyproject.toml", '[project]\ndynamic=["dependencies"]\n[tool.poetry.dependencies]\npython="^3.11"\nflask="^3"\n')
    result = analyze(tmp_path)
    assert result.dependencies == ("python:flask",)
    assert result.frameworks == ("Flask",)
    assert any("Dynamic" in note for note in result.limitations)


def test_language_unknown_dependencies_and_fallback_are_honest(tmp_path) -> None:
    write(tmp_path, "Cargo.toml", '[dependencies]\nserde="1"')
    write(tmp_path, "src/main.rs", "fn main() {}")
    result = analyze(tmp_path, "Inspect repository")
    assert result.languages == ("Rust",)
    assert result.dependencies == ()
    assert result.frameworks == ()
    assert "Cargo.toml" in result.relevant_files
    assert any("Dependency parsing covers" in note for note in result.limitations)


def test_repository_code_is_never_imported_or_executed(tmp_path) -> None:
    source = tmp_path / "source"
    marker = tmp_path / "EXECUTED"
    write(source, "setup.py", f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n")
    prepared = WorkspacePreparer(tmp_path / "workspaces").prepare(source, uuid4())
    assert analyze(prepared.root).languages == ("Python",)
    assert not marker.exists()


def test_empty_repository_has_observed_zero_count_without_invented_languages(tmp_path) -> None:
    result = analyze(tmp_path)
    assert result.inspected_file_count == 0
    assert result.languages == result.frameworks == result.relevant_files == ()
