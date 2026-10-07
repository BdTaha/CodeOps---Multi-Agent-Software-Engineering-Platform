"""Deterministic repository analysis from observed files and declared metadata."""

import json
import re
import tomllib
from pathlib import PurePosixPath

from packaging.requirements import InvalidRequirement, Requirement

from autonomous_engineering.domain.results import RepositoryAnalysis
from autonomous_engineering.tools.repository import RepositoryError, RepositoryReader

LANGUAGES = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust",
    ".java": "Java", ".cs": "C#", ".c": "C", ".cpp": "C++",
    ".rb": "Ruby", ".php": "PHP", ".kt": "Kotlin", ".swift": "Swift",
    ".html": "HTML", ".css": "CSS", ".sql": "SQL", ".sh": "Shell",
    ".ps1": "PowerShell",
}
FRAMEWORKS = {
    "python:fastapi": "FastAPI", "python:starlette": "Starlette",
    "python:django": "Django", "python:flask": "Flask",
    "node:react": "React", "node:vue": "Vue", "node:next": "Next.js",
    "node:express": "Express", "node:@nestjs/core": "NestJS",
    "node:nuxt": "Nuxt", "node:svelte": "Svelte",
}
IMPORTANT_NAMES = {
    "pyproject.toml", "package.json", "cargo.toml", "go.mod", "pom.xml",
    "dockerfile", "compose.yaml", "docker-compose.yml", "readme.md",
    "main.py", "app.py", "manage.py", "index.ts", "index.js",
}
STOP_WORDS = frozenset({
    "the", "and", "for", "with", "this", "that", "from", "into", "fix", "bug",
    "issue", "feature", "implement", "add", "repository", "inspect", "code",
    "please", "should", "when", "not", "are", "can", "support",
})


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9_]{2,}", text.casefold())) - STOP_WORDS


def _dependency_names(path: str, text: str) -> tuple[set[str], list[str]]:
    names: set[str] = set()
    notes: list[str] = []
    basename = PurePosixPath(path).name.casefold()
    try:
        if basename == "package.json":
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError("manifest must be an object")
            for group in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                dependencies = data.get(group, {})
                if not isinstance(dependencies, dict):
                    raise ValueError("dependency section must be an object")
                for name, spec in dependencies.items():
                    if not re.fullmatch(r"(?:@[\w.-]+/)?[\w.-]+", name) or not isinstance(spec, str):
                        raise ValueError("invalid dependency entry")
                    names.add(f"node:{name.casefold()}")
            return names, notes
        requirements: list[str] = []
        if basename == "pyproject.toml":
            data = tomllib.loads(text)
            project = data.get("project", {})
            if not isinstance(project, dict):
                raise ValueError("project must be an object")
            declared = project.get("dependencies", [])
            if not isinstance(declared, list):
                raise ValueError("dependencies must be an array")
            requirements.extend(declared)
            if "dependencies" in project.get("dynamic", []):
                notes.append(f"Dynamic dependencies are not evaluated: {path[:200]}.")
            optional = project.get("optional-dependencies", {})
            if not isinstance(optional, dict):
                raise ValueError("optional dependencies must be a table")
            for group in optional.values():
                if not isinstance(group, list):
                    raise ValueError("dependency groups must be arrays")
                requirements.extend(group)
            poetry = data.get("tool", {}).get("poetry", {})
            for group in (poetry.get("dependencies", {}), poetry.get("dev-dependencies", {})):
                if not isinstance(group, dict):
                    raise ValueError("Poetry dependencies must be a table")
                requirements.extend(name for name in group if name.casefold() != "python")
        elif basename.startswith("requirements") and basename.endswith(".txt"):
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("-"):
                    if len(notes) < 20:
                        notes.append(f"Requirements options/includes are not followed: {path[:200]}.")
                    continue
                requirements.append(line.split(" #", 1)[0])
        else:
            return names, notes
        for requirement in requirements:
            if not isinstance(requirement, str):
                raise ValueError("dependency must be a string")
            parsed = Requirement(requirement)
            normalized = re.sub(r"[-_.]+", "-", parsed.name).casefold()
            # Return names only: direct URL specifications may contain credentials.
            names.add(f"python:{normalized}")
    except (json.JSONDecodeError, tomllib.TOMLDecodeError, InvalidRequirement, ValueError, TypeError, AttributeError, RecursionError):
        return set(), [f"Malformed or unsupported dependency metadata: {path[:200]}; dependencies from this file were omitted."]
    return names, notes


class RepositoryAnalyzer:
    def analyze(self, reader: RepositoryReader, user_request: str) -> RepositoryAnalysis:
        inventory = reader.inventory()
        files = inventory.files
        languages = sorted({LANGUAGES[PurePosixPath(p).suffix.casefold()]
                            for p in files if PurePosixPath(p).suffix.casefold() in LANGUAGES})
        directories = sorted({p.split("/", 1)[0] for p in files if "/" in p})
        layout_components = sorted({part for p in files for part in PurePosixPath(p).parts[:-1]
                                    if part in {"api", "agents", "core", "domain", "tools", "workflows", "infrastructure", "tests"}})
        important = tuple(p for p in files if PurePosixPath(p).name.casefold() in IMPORTANT_NAMES
                          or PurePosixPath(p).name.casefold().startswith("requirements"))[:40]
        query = _tokens(user_request)
        dependencies: set[str] = set()
        notes: list[str] = []
        ranked: list[tuple[int, str]] = []
        total_bytes = 0
        for path in files:
            text = reader.read_text(path)
            total_bytes += len(text.encode("utf-8"))
            if total_bytes > reader.limits.max_total_bytes:
                raise RepositoryError("INSPECTION_LIMIT", "Analyzer text exceeds the total inspection limit.")
            detected, file_notes = _dependency_names(path, text)
            dependencies.update(detected)
            notes.extend(file_notes)
            score = 4 * len(query & _tokens(path.replace("/", " ").replace(".", " ")))
            score += len(query & _tokens(text[:12000]))
            if score:
                ranked.append((score, path))
        frameworks = sorted({FRAMEWORKS[name] for name in dependencies if name in FRAMEWORKS})
        relevant = tuple(path for _, path in sorted(ranked, key=lambda item: (-item[0], item[1]))[:12])
        if not relevant:
            relevant = important[:12]
        summary = (
            f"Inspected {len(files)} UTF-8 text files. Languages by extension: {', '.join(languages) or 'none detected'}. "
            f"Top-level directories containing inspected files: {', '.join(directories[:12]) or 'none'}. "
            f"Declared framework dependencies: {', '.join(frameworks) or 'none detected'}. "
            f"Named layout components: {', '.join(layout_components) or 'none of the recognized names'}. "
            "These are layout and manifest observations; runtime architecture has not been verified."
        )
        return RepositoryAnalysis(
            languages=tuple(languages), frameworks=tuple(frameworks),
            dependencies=tuple(sorted(dependencies)), important_files=important,
            relevant_files=relevant, architecture_summary=summary[:4000],
            inspected_file_count=len(files), top_level_directories=tuple(directories),
            limitations=tuple(dict.fromkeys(notes))[:20] + (
                "Dependency parsing covers pyproject.toml (PEP 621 and basic Poetry), requirements*.txt, and package.json; names include development/optional declarations, not resolved installed versions.",
                "Relevance uses request words matched against paths and the first 12000 characters of each file; fallback files are important-file candidates, not proven issue locations.",
            ),
        )
