"""Local administration: generated temporary credentials, revocation and last-admin guard."""

import secrets
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .access import audit_event, normalize_username
from .auth import PASSWORD_HASHER, AuthStore
from .auth_routes import AuthRoute, Store
from .run_routes import Limit, Offset


Role = Literal['admin', 'builder', 'operator', 'viewer', 'auditor']
router = APIRouter(prefix='/console/users', tags=['Local users'], route_class=AuthRoute)
USER_FIELDS = 'id,username,display_name,role,active,totp_enabled,password_change_required,created_at'


class UserCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    username: str = Field(min_length=1, max_length=120)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: Role

    @field_validator('username', 'display_name')
    @classmethod
    def clean_name(cls, value):
        if value is not None:
            value = ' '.join(value.split())
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                raise ValueError("Invalid text") from None
            if not value or not any(char.isalnum() for char in value) or any(ord(char) < 32 for char in value):
                raise ValueError('Invalid name')
        return value


class UserPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: Role | None = None
    active: bool | None = None

    @field_validator('display_name')
    @classmethod
    def clean_name(cls, value):
        return UserCreate.clean_name(value)


def view(row: dict) -> dict:
    return {**AuthStore.public_user(row), 'totp_enabled': row['totp_enabled'],
            'password_change_required': row['password_change_required'], 'created_at': row['created_at']}


def actor_id(request: Request):
    user = getattr(request.state, 'auth_user', None)
    return user['id'] if user else None


def lock_admin_state(connection, user_id):
    # A common lock prevents two concurrent admin demotions removing the final admin.
    connection.execute('SELECT singleton FROM auth_installation WHERE singleton FOR UPDATE').fetchone()
    user = connection.execute(f'SELECT {USER_FIELDS} FROM auth_users WHERE id=%s FOR UPDATE', (user_id,)).fetchone()
    if not user:
        raise HTTPException(404, 'Compte introuvable')
    return user


def revoke(connection, user_id):
    connection.execute('DELETE FROM auth_sessions WHERE user_id=%s', (user_id,))
    connection.execute('DELETE FROM auth_challenges WHERE user_id=%s', (user_id,))


@router.get('')
def list_users(store: Store, limit: Limit = 100, offset: Offset = 0):
    with store.connect() as connection:
        total = connection.execute('SELECT count(*) AS total FROM auth_users').fetchone()['total']
        rows = connection.execute(f'SELECT {USER_FIELDS} FROM auth_users ORDER BY username LIMIT %s OFFSET %s', (limit, offset)).fetchall()
    return {'items': [view(row) for row in rows], 'total': total, 'limit': limit, 'offset': offset}


@router.post('', status_code=201)
def create_user(payload: UserCreate, request: Request, store: Store):
    username = normalize_username(payload.username)
    display_name = payload.display_name or payload.username
    password = secrets.token_urlsafe(24)
    password_hash = PASSWORD_HASHER.hash(password)
    try:
        with store.connect() as connection:
            connection.execute('SELECT singleton FROM auth_installation WHERE singleton FOR UPDATE').fetchone()
            row = connection.execute(
                f'INSERT INTO auth_users(id,username,display_name,role,password_hash,password_change_required) '
                f'VALUES(%s,%s,%s,%s,%s,true) RETURNING {USER_FIELDS}',
                (uuid4(), username, display_name, payload.role, password_hash),
            ).fetchone()
            connection.execute('UPDATE auth_installation SET bootstrapped=true WHERE singleton')
            audit_event(connection, actor_id(request), 'user.created', str(row['id']), {'role': payload.role})
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, 'Cet identifiant existe déjà') from None
    return {'user': view(row), 'temporary_password': password}


@router.patch('/{user_id}')
def update_user(user_id: UUID, payload: UserPatch, request: Request, store: Store):
    values = payload.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(422, 'Aucune modification')
    with store.connect() as connection:
        previous = lock_admin_state(connection, user_id)
        next_role, next_active = values.get('role', previous['role']), values.get('active', previous['active'])
        if previous['role'] == 'admin' and previous['active'] and (next_role != 'admin' or not next_active):
            other = connection.execute("SELECT 1 FROM auth_users WHERE id<>%s AND role='admin' AND active LIMIT 1", (user_id,)).fetchone()
            if not other:
                raise HTTPException(409, 'Le dernier administrateur actif doit être conservé')
        row = connection.execute(
            f'UPDATE auth_users SET display_name=%s,role=%s,active=%s WHERE id=%s RETURNING {USER_FIELDS}',
            (values.get('display_name', previous['display_name']), next_role, next_active, user_id),
        ).fetchone()
        if next_role != previous['role'] or next_active != previous['active']:
            revoke(connection, user_id)
        audit_event(connection, actor_id(request), 'user.updated', str(user_id),
                    {'previous_role': previous['role'], 'role': next_role, 'active': next_active})
    return view(row)


@router.post('/{user_id}/reset-password')
def reset_password(user_id: UUID, request: Request, store: Store):
    password = secrets.token_urlsafe(24)
    password_hash = PASSWORD_HASHER.hash(password)
    with store.connect() as connection:
        lock_admin_state(connection, user_id)
        row = connection.execute(
            f'UPDATE auth_users SET password_hash=%s,password_change_required=true WHERE id=%s RETURNING {USER_FIELDS}',
            (password_hash, user_id),
        ).fetchone()
        revoke(connection, user_id)
        audit_event(connection, actor_id(request), 'user.password.reset', str(user_id))
    return {'user': view(row), 'temporary_password': password}


@router.post('/{user_id}/reset-2fa')
def reset_two_factor(user_id: UUID, request: Request, store: Store):
    with store.connect() as connection:
        lock_admin_state(connection, user_id)
        revoke(connection, user_id)
        connection.execute('DELETE FROM auth_recovery_codes WHERE user_id=%s', (user_id,))
        row = connection.execute(
            f'UPDATE auth_users SET totp_secret=NULL,totp_enabled=false,totp_last_counter=-1 WHERE id=%s RETURNING {USER_FIELDS}',
            (user_id,),
        ).fetchone()
        audit_event(connection, actor_id(request), 'user.two_factor.reset', str(user_id))
    return view(row)
