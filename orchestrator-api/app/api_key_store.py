"""Revocable personal credentials; API scope can only narrow the owner's live role."""
import re
import secrets
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import Field, field_validator

from .access import audit_event, permissions_for
from .auth import AuthStore, digest
from .self_security import Confirmation, SelfSecurityStore

API_SCOPES = frozenset({'devices.read', 'workflows.read', 'workflows.publish', 'runs.read', 'runs.execute', 'runs.cancel'})
TOKEN_PATTERN = re.compile(r'emk_[A-Za-z0-9_-]{43}')


class KeyCreation(Confirmation):
    request_id: str = Field(pattern=r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
    name: str = Field(min_length=1, max_length=80)
    scopes: list[str] = Field(min_length=1, max_length=6)
    expires_days: int = Field(default=90, ge=1, le=365)

    @field_validator('name', mode='before')
    @classmethod
    def human_name(cls, value):
        if isinstance(value, str):
            value = ' '.join(value.split())
            if any(ord(character) < 32 for character in value):
                raise ValueError('Invalid key name')
            cls.bounded_unicode(value)
        return value

    @field_validator('scopes')
    @classmethod
    def valid_scopes(cls, value):
        if len(set(value)) != len(value) or not set(value) <= API_SCOPES:
            raise ValueError('Unsupported or repeated scope')
        return sorted(value)


class APIKeyStore(SelfSecurityStore):
    @staticmethod
    def public_key(row):
        return {key: str(row[key]) if key == 'id' else row[key] for key in (
            'id', 'name', 'token_prefix', 'scopes', 'created_at', 'expires_at', 'last_used_at', 'revoked_at'
        )}

    def list_keys(self, session, limit=100, offset=0):
        with self.connect() as connection:
            user = self._session_user(connection, session)
            rows = connection.execute(
                'SELECT * FROM personal_api_keys WHERE user_id=%s ORDER BY created_at DESC,id LIMIT %s OFFSET %s',
                (user['id'], limit, offset),
            ).fetchall()
            total = connection.execute('SELECT count(*) AS n FROM personal_api_keys WHERE user_id=%s', (user['id'],)).fetchone()['n']
            return {'items': [self.public_key(row) for row in rows], 'total': total, 'limit': limit, 'offset': offset,
                    'available_scopes': sorted(API_SCOPES.intersection(permissions_for(user['role'])))}

    def create_key(self, session, payload: KeyCreation, ip):
        self._limited(session, ip)
        with self.connect() as connection:
            user = self._session_user(connection, session)
            if not set(payload.scopes) <= set(permissions_for(user['role'])):
                raise HTTPException(403, 'Une clé ne peut pas dépasser les droits de votre rôle')
            if connection.execute('SELECT 1 FROM personal_api_keys WHERE user_id=%s AND request_id=%s',
                                  (user['id'], UUID(payload.request_id))).fetchone():
                raise HTTPException(409, 'Cette clé a déjà été créée. Son secret ne peut pas être affiché de nouveau.')
            active = connection.execute(
                'SELECT count(*) AS n FROM personal_api_keys WHERE user_id=%s AND revoked_at IS NULL AND expires_at>clock_timestamp()',
                (user['id'],),
            ).fetchone()['n']
            if active >= 20:
                raise HTTPException(409, 'Révoquez une clé avant d’en créer une autre (20 clés actives maximum)')
            self._reauthenticate(connection, user, payload, backup_allowed=False)
            secret = 'emk_' + secrets.token_urlsafe(32)
            row = connection.execute(
                'INSERT INTO personal_api_keys(id,user_id,request_id,name,token_hash,token_prefix,scopes,expires_at) '
                "VALUES(%s,%s,%s,%s,%s,%s,%s,clock_timestamp()+%s*interval '1 day') RETURNING *",
                (uuid4(), user['id'], UUID(payload.request_id), payload.name, digest(secret), secret[:12], payload.scopes, payload.expires_days),
            ).fetchone()
            audit_event(connection, user['id'], 'account.api_key.created', str(row['id']))
            return {'key': self.public_key(row), 'secret': secret, 'shown_once': True}

    def revoke_key(self, session, key_id):
        with self.connect() as connection:
            user = self._session_user(connection, session)
            row = connection.execute('SELECT * FROM personal_api_keys WHERE id=%s AND user_id=%s FOR UPDATE', (key_id, user['id'])).fetchone()
            if not row:
                raise HTTPException(404, 'Clé introuvable')
            if row['revoked_at'] is None:
                connection.execute('UPDATE personal_api_keys SET revoked_at=clock_timestamp() WHERE id=%s', (key_id,))
                audit_event(connection, user['id'], 'account.api_key.revoked', str(key_id))
            return {'ok': True}

    def authenticate_key(self, authorization):
        scheme, _, token = (authorization or '').partition(' ')
        if scheme.lower() != 'bearer' or not TOKEN_PATTERN.fullmatch(token):
            raise HTTPException(401, 'Clé API personnelle requise', headers={'WWW-Authenticate': 'Bearer'})
        blocked = False
        with self.connect() as connection:
            row = connection.execute(
                'SELECT k.id AS key_id,k.scopes,u.* FROM personal_api_keys k JOIN auth_users u ON u.id=k.user_id '
                'WHERE k.token_hash=%s AND k.revoked_at IS NULL AND k.expires_at>clock_timestamp() '
                'AND u.active AND u.totp_enabled AND NOT u.password_change_required', (digest(token),),
            ).fetchone()
            if not row:
                raise HTTPException(401, 'Clé API expirée ou révoquée', headers={'WWW-Authenticate': 'Bearer'})
            counter = connection.execute(
                'INSERT INTO auth_rate_limits(bucket_key,attempts) VALUES(%s,1) ON CONFLICT(bucket_key) DO UPDATE SET '
                "attempts=CASE WHEN auth_rate_limits.window_start<clock_timestamp()-interval '1 minute' "
                'THEN 1 ELSE auth_rate_limits.attempts+1 END, '
                "window_start=CASE WHEN auth_rate_limits.window_start<clock_timestamp()-interval '1 minute' "
                'THEN clock_timestamp() ELSE auth_rate_limits.window_start END RETURNING attempts',
                (digest('personal-api:' + str(row['key_id'])),),
            ).fetchone()
            blocked = counter['attempts'] > 600
            connection.execute('UPDATE personal_api_keys SET last_used_at=clock_timestamp() WHERE id=%s', (row['key_id'],))
            user = AuthStore.public_user(row)
            principal = {'key_id': str(row['key_id']), 'user': user, 'scopes': sorted(set(row['scopes']).intersection(user['permissions']))}
        if blocked:
            raise HTTPException(429, 'Limite de la clé API atteinte', headers={'Retry-After': '60'})
        return principal
