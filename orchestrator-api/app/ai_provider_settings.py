"""Shared planner settings and the encrypted installation DeepSeek key."""

from ipaddress import ip_address, ip_network
import json
import os
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from .access import audit_event
from .ai_provider_probe import probe_openai, probe_shared_model
from .auth import AuthConfig, SESSION_COOKIE, auth_enabled
from .auth_routes import AuthRoute, client_ip
from .self_security import SelfSecurityStore


Provider = Literal['openai', 'ollama', 'deepseek']
DEFAULT_DEEPSEEK_MODEL = 'deepseek-flash'
_MODEL_PATTERN = r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}'
_PRIVATE_NETWORKS = tuple(ip_network(network) for network in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7'))


def _ollama_endpoint(value: str) -> httpx.URL | None:
    if not value or len(value) > 512 or not value.isascii() or re.search(r'[\x00-\x20\x7f?#%\\]', value):
        return None
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
        if (parsed.scheme not in {'http', 'https'} or not host or port == 0
                or parsed.username is not None or parsed.password is not None or parsed.path not in {'', '/'}):
            return None
        if host not in {'localhost', 'host.docker.internal', 'ollama'}:
            address = ip_address(host)
            address = getattr(address, 'ipv4_mapped', None) or address
            if not address.is_loopback and not any(address in network for network in _PRIVATE_NETWORKS):
                return None
        return httpx.URL(scheme=parsed.scheme, host=host, port=port, path='')
    except ValueError:
        return None


def _model(value: str, *, local: bool = False) -> str | None:
    if not re.fullmatch(_MODEL_PATTERN, value) or local and re.search(r'(?:[:-]cloud)(?::|$)', value, re.I):
        return None
    return value


def _valid_key(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[!-~]{1,512}', value) is not None


class AiProviderPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    active_provider: Provider | None = None
    ollama_url: str | None = Field(default=None, max_length=512)
    ollama_model: str | None = Field(default=None, max_length=128)
    deepseek_key: SecretStr | None = Field(default=None, max_length=512)
    deepseek_model: str | None = Field(default=None, max_length=128)

    @field_validator('ollama_url', 'ollama_model', 'deepseek_model', mode='before')
    @classmethod
    def trim(cls, value):
        return value.strip() or None if isinstance(value, str) else value

    @field_validator('deepseek_key')
    @classmethod
    def validate_key(cls, value):
        if value is None:
            return None
        key = value.get_secret_value().strip()
        if not _valid_key(key):
            raise ValueError('Invalid DeepSeek API key')
        return SecretStr(key)

    @model_validator(mode='after')
    def validate_provider(self):
        if 'active_provider' in self.model_fields_set and self.active_provider is None:
            raise ValueError('Select a provider')
        if self.ollama_url is not None and _ollama_endpoint(self.ollama_url) is None:
            raise ValueError('Invalid local Ollama URL')
        if self.ollama_model is not None and _model(self.ollama_model, local=True) is None:
            raise ValueError('Invalid local Ollama model')
        if self.deepseek_model is not None and _model(self.deepseek_model) is None:
            raise ValueError('Invalid DeepSeek model')
        return self


class AiProviderTest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    provider: Provider


def _ollama(row):
    return (_ollama_endpoint(row.get('ollama_url') or os.getenv('EMULYTIX_OLLAMA_URL', '').strip()),
            _model(row.get('ollama_model') or os.getenv('EMULYTIX_OLLAMA_MODEL', '').strip(), local=True))


def _deepseek_model(row):
    return _model(row.get('deepseek_model') or os.getenv('EMULYTIX_DEEPSEEK_MODEL', '').strip() or DEFAULT_DEEPSEEK_MODEL)


def _deepseek_env_key():
    key = os.getenv('EMULYTIX_DEEPSEEK_API_KEY', '').strip()
    return key if _valid_key(key) else None


def _encrypt_deepseek_key(cipher, key):
    payload = {'provider': 'deepseek', 'key': key}
    return cipher.encrypt(json.dumps(payload).encode()).decode()


def _decrypt_deepseek_key(cipher, encrypted):
    try:
        value = json.loads(cipher.decrypt(encrypted.encode()))
    except ValueError:
        raise InvalidToken from None
    if not isinstance(value, dict) or value.get('provider') != 'deepseek' or not _valid_key(value.get('key')):
        raise InvalidToken
    return value['key']


def external_planner_settings(provider, row=None, *, cipher=None):
    row = row or {}
    if provider == 'ollama':
        endpoint, model = _ollama(row)
        if endpoint and model:
            return {'model': model, 'url': endpoint.copy_with(path='/api/chat'), 'headers': {}}
    if provider == 'deepseek':
        model = _deepseek_model(row)
        encrypted = row.get('deepseek_key_ciphertext')
        key = _decrypt_deepseek_key(cipher, encrypted) if encrypted else _deepseek_env_key()
        if model and key:
            return {'model': model, 'url': 'https://api.deepseek.com/chat/completions', 'headers': {'Authorization': f'Bearer {key}'}}
    return None


def provider_row(connection):
    return connection.execute('SELECT * FROM ai_provider_settings WHERE singleton').fetchone()


def _provider_view(row, can_edit):
    endpoint, model = _ollama(row)
    has_saved_key = bool(row['deepseek_key_ciphertext'])
    return {'active_provider': row['active_provider'], 'can_edit': can_edit,
            'ollama': {'url': str(endpoint) if endpoint else None, 'model': model, 'configured': bool(endpoint and model)},
            'deepseek': {'model': _deepseek_model(row) or DEFAULT_DEEPSEEK_MODEL,
                         'has_key': has_saved_key or bool(_deepseek_env_key()), 'has_saved_key': has_saved_key}}


class AiProviderSettingsStore(SelfSecurityStore):
    def status(self, session):
        with self.connect() as connection:
            user = self._session_user(connection, session)
            return _provider_view(provider_row(connection), user['role'] == 'admin')

    def update(self, session, payload: AiProviderPatch):
        with self.connect() as connection:
            user = self._session_user(connection, session)
            if user['role'] != 'admin':
                raise HTTPException(403, 'Seul un administrateur peut modifier les fournisseurs IA.')
            fields = payload.model_fields_set
            if not fields:
                return _provider_view(provider_row(connection), True)
            values = {name: getattr(payload, name)
                      for name in ('active_provider', 'ollama_url', 'ollama_model', 'deepseek_model') if name in fields}
            if 'deepseek_key' in fields:
                key = payload.deepseek_key
                values['deepseek_key_ciphertext'] = _encrypt_deepseek_key(self.config.cipher, key.get_secret_value()) if key else None
            assignments = ', '.join(f'{name}=%s' for name in values)
            row = connection.execute(f'UPDATE ai_provider_settings SET {assignments} WHERE singleton RETURNING *',
                                     tuple(values.values())).fetchone()
            if (payload.active_provider in ('ollama', 'deepseek')
                    and not external_planner_settings(payload.active_provider, row, cipher=self.config.cipher)):
                raise HTTPException(409, {'code': 'provider_unconfigured'})
            self._live_session(connection, user)
            audit_event(connection, user['id'], 'ai_providers.updated')
            return _provider_view(row, True)

    def test_connection(self, session, provider: Provider, ip):
        with self.connect() as connection:
            user = self._session_user(connection, session)
            if provider != 'openai' and user['role'] != 'admin':
                raise HTTPException(403, 'Seul un administrateur peut tester un fournisseur partagé.')
            row = provider_row(connection) if provider != 'openai' else None
        bucket, ceiling = ('journey-generation', 10) if provider == 'openai' else ('ai-provider-test', 5)
        try:
            self.limit(bucket, str(user['id']), ip, maximum=ceiling)
        except HTTPException as error:
            if error.status_code != 429:
                raise
            raise HTTPException(429, {'code': 'provider_busy'}, headers=error.headers) from None
        if provider == 'openai':
            probe_openai(self.config, session)
        else:
            try:
                settings = external_planner_settings(provider, row, cipher=self.config.cipher)
            except InvalidToken:
                raise HTTPException(503, {'code': 'provider_unavailable'}) from None
            probe_shared_model(provider, settings)
            with self.connect() as connection:
                current = self._session_user(connection, session)
                if current['id'] != user['id'] or current['role'] != 'admin':
                    raise HTTPException(403, 'Droits insuffisants')
        return {'provider': provider, 'status': 'ok'}


router = APIRouter(prefix='/console/account/ai-providers', tags=['AI provider preferences'], route_class=AuthRoute)


def ai_provider_store():
    if not auth_enabled():
        raise HTTPException(503, 'Authentification non activée')
    return AiProviderSettingsStore(AuthConfig.load())


Store = Annotated[AiProviderSettingsStore, Depends(ai_provider_store)]


@router.get('')
def status(request: Request, store: Store):
    return store.status(request.cookies.get(SESSION_COOKIE))


@router.patch('')
def update(payload: AiProviderPatch, request: Request, store: Store):
    return store.update(request.cookies.get(SESSION_COOKIE), payload)


@router.post('/test')
def test_provider(payload: AiProviderTest, request: Request, store: Store):
    return store.test_connection(request.cookies.get(SESSION_COOKIE), payload.provider, client_ip(request))
