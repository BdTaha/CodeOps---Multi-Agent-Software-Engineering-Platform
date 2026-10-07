"""Validated configuration loaded from environment variables and .env."""

from typing import Literal
from pathlib import Path

from pydantic import Field, field_validator, SecretStr
from urllib.parse import urlsplit
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ASE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(
        default="Autonomous Software Engineering Multi-Agent System",
        min_length=1,
    )
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    workspace_root: Path = Path(".workspaces")
    ollama_model: str | None = Field(default=None, min_length=1, max_length=200)
    ollama_base_url: str = "http://127.0.0.1:11434"
    planner_timeout_seconds: float = Field(default=180, gt=0, le=600, allow_inf_nan=False)
    test_timeout_seconds: float = Field(default=60, gt=0, le=300, allow_inf_nan=False)
    database_url: SecretStr = SecretStr("sqlite:///engineering.db")
    test_backend: Literal["docker", "local"] = "docker"
    test_framework: Literal["unittest", "pytest", "npm"] = "unittest"
    docker_image: str = Field(default="ase-runner:local", min_length=1, max_length=300)
    docker_executable: str = Field(default="docker", min_length=1, max_length=4096)
    worker_poll_seconds: float = Field(default=1, gt=0, le=30)
    lease_seconds: int = Field(default=60, ge=15, le=600)
    github_token: SecretStr | None = None
    repository_root: Path = Path(".")

    @field_validator("ollama_base_url")
    @classmethod
    def local_ollama_only(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment):
            raise ValueError("Ollama must use a local loopback HTTP URL without credentials or a path")
        # Validate the port too (urlsplit raises for invalid port ranges).
        parsed.port
        return value.rstrip("/")

    @field_validator("ollama_model")
    @classmethod
    def clean_model(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or any(char.isspace() for char in value)):
            raise ValueError("Ollama model must be a nonblank model tag without whitespace")
        if value is not None and (value.endswith(":cloud") or value.endswith("-cloud")):
            raise ValueError("Use a locally pulled model, not an Ollama cloud model")
        return value
