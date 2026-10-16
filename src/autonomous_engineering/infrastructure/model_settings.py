"""Durable, revisioned provider settings. Credentials never leave this boundary."""
import ctypes
import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Literal
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from sqlalchemy import Column, Integer, MetaData, String, Table, Text, select, update, delete, true

from autonomous_engineering.infrastructure.custom_models import validate_endpoint
from autonomous_engineering.domain.models import ReasoningPolicy, ProviderError
from autonomous_engineering.infrastructure.nvidia_reasoning import reasoning_control

metadata = MetaData()
connections = Table('model_connections', metadata,
    Column('id', String(36), primary_key=True), Column('revision', Integer, nullable=False),
    Column('profile', Text, nullable=False), Column('encrypted_key', Text))
routes = Table('model_route_settings', metadata,
    Column('id', Integer, primary_key=True), Column('revision', Integer, nullable=False), Column('route', Text))
_key_lock = threading.Lock()


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    protocol: Literal['nvidia', 'ollama', 'openai', 'anthropic', 'gemini']
    base_url: str = Field(min_length=1, max_length=500)
    api_key: SecretStr | None = Field(default=None, repr=False)
    clear_key: bool = False
    structured_mode: Literal['prompt', 'json_object', 'json_schema'] = 'prompt'
    token_parameter: Literal['max_tokens', 'max_completion_tokens'] = 'max_tokens'
    send_temperature: bool = True
    reasoning_policy: ReasoningPolicy = 'provider_default'
    revision: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def reasoning_valid(self):
        if self.protocol != 'nvidia' and self.reasoning_policy != 'provider_default':
            raise ValueError('Reasoning policy is supported only for NVIDIA NIM connections.')
        return self

    @field_validator('name')
    @classmethod
    def name_valid(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value): raise ValueError('Enter a valid connection name.')
        return value

    @field_validator('api_key')
    @classmethod
    def key_valid(cls, value):
        if value and (len(value.get_secret_value()) > 8192 or any(ord(c) <= 32 or ord(c) >= 127 for c in value.get_secret_value())):
            raise ValueError('Use an API key without whitespace or control characters.')
        return value

    @field_validator('base_url')
    @classmethod
    def url_valid(cls, value):
        return validate_endpoint(value)


class RouteInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1)
    primary_connection: str = Field(min_length=1, max_length=36)
    primary_model: str = Field(min_length=1, max_length=200)
    fallback_enabled: bool = False
    fallback_connection: str | None = Field(default=None, max_length=36)
    fallback_model: str | None = Field(default=None, max_length=200)

    @field_validator('primary_model', 'fallback_model')
    @classmethod
    def model_valid(cls, value):
        if value is None: return value
        if not value.strip() or any(ord(c) < 32 for c in value): raise ValueError('Enter a valid model ID.')
        return value.strip()


class SettingsConflict(ValueError): pass


class SelectedModelTestInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model: str = Field(min_length=1, max_length=200)
    revision: int = Field(ge=1)

    @field_validator('model')
    @classmethod
    def model_valid(cls, value):
        return RouteInput.model_valid(value)


def _protect(data, decrypt=False):
    # DPAPI binds the generated master key to the Windows account running CodeOps.
    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('The credential encryption key is unavailable to this account.')
    try: return ctypes.string_at(target.data, target.size)
    finally: ctypes.windll.kernel32.LocalFree(target.data)


class ModelSettingsStore:
    def __init__(self, settings, engine):
        self.settings, self.engine = settings, engine
        metadata.create_all(engine)
        with engine.begin() as db:
            if db.execute(select(routes.c.id)).first() is None:
                # Initialization is idempotent across API and worker starts.
                from sqlalchemy.exc import IntegrityError
                try:
                    with db.begin_nested(): db.execute(routes.insert().values(id=1, revision=1, route=None))
                except IntegrityError: pass

    def cipher(self):
        configured = self.settings.model_settings_encryption_key
        if configured:
            try: return Fernet(configured.get_secret_value().encode('ascii'))
            except (ValueError, UnicodeError): raise ValueError('Invalid credential encryption key configuration.') from None
        identity = hashlib.sha256(self.settings.database_url.get_secret_value().encode()).hexdigest()[:20]
        path = Path(self.settings.workspace_root) / 'model-credentials' / (identity+'.key')
        with _key_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                key = Fernet.generate_key()
                encoded = _protect(key) if os.name == 'nt' else key
                # Atomic publication; competing processes use the first complete key.
                temp = path.with_name(str(uuid4())+'.tmp')
                with open(temp, 'xb') as file:
                    if os.name != 'nt': os.chmod(temp, 0o600)
                    file.write(encoded)
                try: os.link(temp, path)
                except FileExistsError: pass
                finally: temp.unlink()
            data = path.read_bytes()
        try: return Fernet(_protect(data, True) if os.name == 'nt' else data)
        except (ValueError, OSError): raise ValueError('The credential encryption key is unavailable.') from None

    def snapshot(self):
        with self.engine.connect() as db:
            rows = db.execute(select(routes.c.route, routes.c.revision.label('route_revision'), connections)
                .select_from(routes.outerjoin(connections, true()))).mappings().all()
        return {'connections': [self.public(row) for row in rows if row['id']],
                'route': json.loads(rows[0]['route']) if rows[0]['route'] else None,
                'revision': rows[0]['route_revision'], 'locked': self.settings.model_settings_locked}

    @staticmethod
    def public(row):
        profile = json.loads(row['profile'])
        profile.setdefault('reasoning_policy', 'provider_default')
        return {'id': row['id'], 'revision': row['revision'], **profile, 'has_key': bool(row['encrypted_key'])}

    def profile(self, connection_id, db=None, secrets=False):
        if db is None:
            with self.engine.connect() as connection: return self.profile(connection_id, connection, secrets)
        row = db.execute(select(connections).where(connections.c.id == connection_id)).mappings().first()
        if row is None: raise ValueError('Connection not found.')
        result = self.public(row)
        if secrets:
            try: result['key'] = self.cipher().decrypt(row['encrypted_key'].encode()).decode() if row['encrypted_key'] else None
            except InvalidToken: raise ValueError('Saved credentials cannot be decrypted. Re-enter the API key.') from None
        return result

    def writable(self):
        if self.settings.model_settings_locked: raise ValueError('Model settings are locked by the administrator.')

    @staticmethod
    def lock(db):
        # A no-op write acquires a SQLite write lock as well as a PostgreSQL row
        # lock. SELECT FOR UPDATE alone cannot serialize SQLite route/deletion races.
        db.execute(update(routes).where(routes.c.id == 1).values(revision=routes.c.revision))

    def save(self, data, connection_id=None):
        self.writable()
        profile = data.model_dump(exclude={'api_key', 'clear_key', 'revision'})
        if data.protocol == 'nvidia' and data.base_url != 'https://integrate.api.nvidia.com/v1':
            raise ValueError('NVIDIA NIM uses https://integrate.api.nvidia.com/v1. Use OpenAI-compatible for other endpoints.')
        if data.protocol == 'ollama':
            from autonomous_engineering.core.config import Settings
            Settings.local_ollama_only(data.base_url)
        if data.protocol in ('anthropic', 'gemini') and data.structured_mode != 'prompt':
            raise ValueError('Use prompt mode for this protocol.')
        encrypted = self.cipher().encrypt(data.api_key.get_secret_value().encode()).decode() if data.api_key else None
        with self.engine.begin() as db:
            self.lock(db)
            if connection_id:
                old = self.profile(connection_id, db)
                if old['revision'] != data.revision: raise SettingsConflict('Connection changed. Refresh and try again.')
                saved_route = json.loads(db.execute(select(routes.c.route)).scalar_one() or '{}')
                for which in ('primary', 'fallback'):
                    if saved_route.get(which+'_connection') == connection_id and (which == 'primary' or saved_route.get('fallback_enabled')):
                        self.validate_reasoning(profile, saved_route[which+'_model'])
                values = {'profile': json.dumps(profile), 'revision': old['revision']+1}
                if data.api_key or data.clear_key: values['encrypted_key'] = encrypted
                result = db.execute(update(connections).where(connections.c.id == connection_id, connections.c.revision == data.revision).values(**values))
                if result.rowcount != 1: raise SettingsConflict('Connection changed. Refresh and try again.')
            else:
                connection_id = str(uuid4())
                db.execute(connections.insert().values(id=connection_id, revision=1, profile=json.dumps(profile), encrypted_key=encrypted))
            return self.profile(connection_id, db)

    def set_route(self, data=None, revision=None):
        self.writable()
        with self.engine.begin() as db:
            self.lock(db)
            if data:
                pairs = [(data.primary_connection, data.primary_model)]
                if data.fallback_enabled:
                    if not data.fallback_connection or not data.fallback_model: raise ValueError('Choose a fallback connection and model.')
                    pairs.append((data.fallback_connection, data.fallback_model))
                if len(pairs) == 2 and pairs[0] == pairs[1]: raise ValueError('Primary and fallback must use different models or connections.')
                for connection_id, model in pairs:
                    profile = self.profile(connection_id, db)
                    self.validate_reasoning(profile, model)
                    if profile['protocol'] != 'ollama' and not profile['has_key'] and not profile['base_url'].startswith(('http://localhost', 'http://127.', 'http://[::1]')):
                        raise ValueError('Add an API key to the selected hosted connection.')
                    if profile['protocol'] == 'ollama' and (any(c.isspace() for c in model) or model.endswith((':cloud', '-cloud'))):
                        raise ValueError('Choose a locally pulled Ollama model.')
            result = db.execute(update(routes).where(routes.c.id == 1, routes.c.revision == (data.revision if data else revision))
                .values(revision=routes.c.revision+1, route=json.dumps(data.model_dump(exclude={'revision'})) if data else None))
            if result.rowcount != 1: raise SettingsConflict('Routing changed. Refresh and try again.')
        return self.snapshot()

    @staticmethod
    def validate_reasoning(profile, model):
        if profile['protocol'] == 'nvidia':
            try: reasoning_control(model, profile.get('reasoning_policy', 'provider_default'))
            except ProviderError as exc: raise ValueError(str(exc)) from None

    def remove(self, connection_id, revision):
        self.writable()
        with self.engine.begin() as db:
            self.lock(db)
            row = db.execute(select(routes)).mappings().one()
            route = json.loads(row['route']) if row['route'] else {}
            if connection_id in (route.get('primary_connection'), route.get('fallback_connection')):
                raise ValueError('Select another route before deleting this connection.')
            result = db.execute(delete(connections).where(connections.c.id == connection_id, connections.c.revision == revision))
            if result.rowcount != 1: raise SettingsConflict('Connection changed or was removed. Refresh and try again.')

    def runtime(self, secrets=True):
        if self.settings.model_settings_locked: return None
        with self.engine.connect() as db:
            rows = db.execute(select(routes.c.route, connections).select_from(routes.outerjoin(connections, true()))).mappings().all()
        if not rows[0]['route']: return None
        route = json.loads(rows[0]['route'])
        ids = {route['primary_connection']}
        if route['fallback_enabled']: ids.add(route.get('fallback_connection'))
        profiles = {}
        for row in rows:
            if row['id'] not in ids: continue
            profile = self.public(row)
            if secrets:
                try: profile['key'] = self.cipher().decrypt(row['encrypted_key'].encode()).decode() if row['encrypted_key'] else None
                except InvalidToken: raise ValueError('Saved credentials cannot be decrypted. Re-enter the API key.') from None
            profiles[row['id']] = profile
        return route, profiles


def attach_model_settings(settings, engine):
    settings._model_settings_store = ModelSettingsStore(settings, engine)
    return settings._model_settings_store
