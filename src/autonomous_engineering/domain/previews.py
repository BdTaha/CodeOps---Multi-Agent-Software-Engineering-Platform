"""Explicit single-container local preview contracts. No host commands or secrets."""
import re
from typing import Literal
from pydantic import Field, StrictBool, field_validator, model_validator
from autonomous_engineering.domain.base import DomainModel

ACTIVE_PREVIEWS = ('queued', 'building', 'starting', 'ready', 'stopping')

class PreviewProfileInput(DomainModel):
    revision: int = Field(default=0, ge=0)
    name: str = Field(default='Local preview', min_length=1, max_length=120)
    preview_type: Literal['web', 'api', 'static', 'none'] = 'none'
    runtime: Literal['python', 'node'] = 'python'
    enabled: StrictBool = False
    build_commands: tuple[tuple[str, ...], ...] = Field(default=(), max_length=8)
    start_command: tuple[str, ...] = Field(default=(), max_length=64)
    container_port: int = Field(default=8000, ge=1, le=65535)
    health_path: str = Field(default='/', max_length=500)
    open_path: str = Field(default='/', max_length=500)
    environment: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=60, ge=5, le=300)
    ttl_minutes: int = Field(default=30, ge=1, le=120)
    build_network: StrictBool = False
    requires_external_services: StrictBool = False

    @field_validator('build_commands', 'start_command')
    @classmethod
    def argv(cls, commands):
        groups = commands if commands and isinstance(commands[0], tuple) else (commands,)
        for command in groups:
            if not command or len(command) > 64:
                if commands: raise ValueError('Commands must be nonempty argv arrays of at most 64 arguments.')
                continue
            if any(not arg or len(arg) > 2000 or '\x00' in arg or '\n' in arg or '\r' in arg for arg in command):
                raise ValueError('Command arguments must be bounded single-line strings.')
            if command[0].lower() in {'sh','bash','cmd','cmd.exe','powershell','pwsh','docker','sudo','su'}:
                raise ValueError('Shell/privilege/container wrappers are unsupported; use structured executable arguments.')
            if '/' in command[0] or '\\' in command[0]:
                raise ValueError('Use an executable name from the configured container runtime.')
        return commands

    @field_validator('health_path', 'open_path')
    @classmethod
    def local_path(cls, value):
        if not value.startswith('/') or value.startswith('//') or any(c.isspace() or ord(c)<32 for c in value) or any(c in value for c in ('\\','#','?','%')):
            raise ValueError('Paths must be local absolute URL paths without authority, query or escapes.')
        return value

    @field_validator('environment')
    @classmethod
    def nonsecret_environment(cls, values):
        if len(values) > 20: raise ValueError('At most 20 non-secret environment values are supported.')
        for key, value in values.items():
            if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}', key): raise ValueError('Environment names must use uppercase identifier syntax.')
            if (re.search(r'TOKEN|SECRET|PASSWORD|CREDENTIAL|PRIVATE|API_KEY|ACCESS_KEY',key)
                    or key.startswith(('AWS_','GITHUB_','SSH_','DOCKER_','ASE_'))
                    or key in {'PATH','HOME','PYTHONPATH','PYTHONHOME','LD_PRELOAD','LD_LIBRARY_PATH','NODE_OPTIONS','NPM_CONFIG_USERCONFIG','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY'}):
                raise ValueError('Secrets and runtime-control environment names are not supported.')
            if len(value) > 500 or any(c in value for c in ('\x00','\r','\n')): raise ValueError('Environment values must be bounded single-line non-secret values.')
        return values

    @model_validator(mode='after')
    def runnable(self):
        if self.preview_type != 'none' and not self.start_command:
            raise ValueError('An explicit start command is required for an interactive profile.')
        return self
