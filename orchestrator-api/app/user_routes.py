"""Local user identities, directory filters and administrative access changes."""

import secrets
from typing import Annotated, Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field, field_validator, model_validator

from .access import audit_event, normalize_username
from .admin_guard import lock_admin_actor
from .auth import PASSWORD_HASHER, AuthStore
from .auth_routes import AuthRoute, Store
from .run_routes import Limit, Offset
from .user_identity import ProfilePatch, clean_name, identity_conflict, identity_values


Role = Literal['admin', 'builder', 'operator', 'viewer', 'auditor']
router = APIRouter(prefix='/console/users', tags=['Local users'], route_class=AuthRoute)
USER_FIELDS = ('id,username,display_name,first_name,last_name,email,role,active,totp_enabled,'
               'password_change_required,created_at,last_login_at,password_changed_at')
USER_VIEW_SQL = f"""
SELECT {','.join('u.' + field for field in USER_FIELDS.split(','))},
       COALESCE(s.active_sessions,0) AS active_sessions,
       COALESCE(r.recovery_codes_remaining,0) AS recovery_codes_remaining
FROM auth_users u
LEFT JOIN (SELECT user_id,count(*) AS active_sessions FROM auth_sessions
           WHERE expires_at>clock_timestamp() GROUP BY user_id) s ON s.user_id=u.id
LEFT JOIN (SELECT user_id,count(*) AS recovery_codes_remaining FROM auth_recovery_codes GROUP BY user_id) r ON r.user_id=u.id
"""


class UserCreate(ProfilePatch):
    username: str | None = Field(default=None, min_length=1, max_length=120)
    display_name: str | None = Field(default=None, min_length=1, max_length=241)
    role: Role

    @field_validator('username', 'display_name')
    @classmethod
    def valid_label(cls, value):
        return clean_name(value) if value is not None else None

    @model_validator(mode='after')
    def named_account(self):
        if not self.username and not self.first_name and not self.last_name:
            raise ValueError('A name or username is required')
        return self


class UserPatch(ProfilePatch):
    display_name: str | None = Field(default=None, min_length=1, max_length=241)
    role: Role | None = None
    active: bool | None = None

    @field_validator('display_name')
    @classmethod
    def valid_label(cls, value):
        return clean_name(value) if value is not None else None


def view(row: dict) -> dict:
    return {**AuthStore.public_user(row), 'totp_enabled': row['totp_enabled'],
            'password_change_required': row['password_change_required'], 'created_at': row['created_at'],
            'last_login_at': row['last_login_at'], 'password_changed_at': row['password_changed_at'],
            'active_sessions': row.get('active_sessions', 0), 'recovery_codes_remaining': row.get('recovery_codes_remaining', 0)}


def get_user_view(connection, user_id) -> dict:
    row = connection.execute(USER_VIEW_SQL + ' WHERE u.id=%s', (user_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Compte introuvable')
    return view(row)


def lock_admin_state(connection, user_id):
    # Serialize changes across administrators without blocking audit foreign-key checks.
    connection.execute('SELECT singleton FROM auth_installation WHERE singleton FOR UPDATE').fetchone()
    user = connection.execute(f'SELECT {USER_FIELDS} FROM auth_users WHERE id=%s FOR NO KEY UPDATE', (user_id,)).fetchone()
    if not user:
        raise HTTPException(404, 'Compte introuvable')
    return user


def ensure_other_ready_admin(connection, user_id):
    other = connection.execute(
        "SELECT 1 FROM auth_users WHERE id<>%s AND role='admin' AND active AND totp_enabled AND NOT password_change_required LIMIT 1",
        (user_id,),
    ).fetchone()
    if not other:
        raise HTTPException(409, {'code': 'last_admin_required'})


def revoke(connection, user_id):
    connection.execute('DELETE FROM auth_sessions WHERE user_id=%s', (user_id,))
    connection.execute('DELETE FROM auth_challenges WHERE user_id=%s', (user_id,))


@router.get('')
def list_users(store: Store, limit: Limit = 100, offset: Offset = 0,
               q: Annotated[str, Query(max_length=320)] = '', role: Role | Literal['all'] = 'all',
               active: Literal['all', 'active', 'inactive'] = 'all',
               two_factor: Literal['all', 'enabled', 'pending'] = 'all',
               onboarding: Literal['all', 'required', 'ready'] = 'all'):
    filters, parameters = [], []
    try:
        q.encode('utf-8')
    except UnicodeEncodeError:
        raise HTTPException(422, 'Recherche invalide') from None
    if '\x00' in q:
        raise HTTPException(422, 'Recherche invalide')
    if q.strip():
        filters.append("strpos(lower(concat_ws(' ',u.username,u.display_name,u.first_name,u.last_name,u.email)),lower(%s))>0")
        parameters.append(' '.join(q.split()))
    if role != 'all':
        filters.append('u.role=%s')
        parameters.append(role)
    if active != 'all':
        filters.append('u.active=%s')
        parameters.append(active == 'active')
    if two_factor != 'all':
        filters.append('u.totp_enabled=%s')
        parameters.append(two_factor == 'enabled')
    if onboarding != 'all':
        filters.append('(u.password_change_required OR NOT u.totp_enabled)=%s')
        parameters.append(onboarding == 'required')
    where = ' WHERE ' + ' AND '.join(filters) if filters else ''
    with store.connect() as connection:
        total = connection.execute('SELECT count(*) AS total FROM auth_users u' + where, parameters).fetchone()['total']
        rows = connection.execute(USER_VIEW_SQL + where + ' ORDER BY u.username,u.id LIMIT %s OFFSET %s',
                                  [*parameters, limit, offset]).fetchall()
    return {'items': [view(row) for row in rows], 'total': total, 'limit': limit, 'offset': offset}


@router.get('/{user_id}')
def user_details(user_id: UUID, store: Store):
    with store.connect() as connection:
        return get_user_view(connection, user_id)


def available_username(connection, label):
    base = normalize_username(label)
    candidate, suffix = base, 1
    while connection.execute('SELECT 1 FROM auth_users WHERE username=%s', (candidate,)).fetchone():
        suffix += 1
        tail = f'-{suffix}'
        candidate = base[:64 - len(tail)] + tail
    return candidate


@router.post('', status_code=201)
def create_user(payload: UserCreate, request: Request, store: Store):
    full_name = ' '.join(filter(None, (payload.first_name, payload.last_name)))
    display_name = full_name or payload.display_name or payload.username
    password = secrets.token_urlsafe(24)
    password_hash = PASSWORD_HASHER.hash(password)
    try:
        with store.connect() as connection:
            actor = lock_admin_actor(connection, request)
            username = normalize_username(payload.username) if payload.username else available_username(
                connection, '.'.join(filter(None, (payload.first_name, payload.last_name))),
            )
            row = connection.execute(
                'INSERT INTO auth_users(id,username,display_name,first_name,last_name,email,role,password_hash,password_change_required) '
                'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,true) RETURNING id',
                (uuid4(), username, display_name, payload.first_name, payload.last_name, payload.email, payload.role, password_hash),
            ).fetchone()
            connection.execute('UPDATE auth_installation SET bootstrapped=true WHERE singleton')
            audit_event(connection, actor, 'user.created', str(row['id']), {'role': payload.role})
            user = get_user_view(connection, row['id'])
    except psycopg.errors.UniqueViolation as error:
        raise identity_conflict(error) from None
    return {'user': user, 'temporary_password': password}


@router.patch('/{user_id}')
def update_user(user_id: UUID, payload: UserPatch, request: Request, store: Store):
    changes = {key: value for key, value in payload.model_dump(exclude_unset=True).items() if value is not None or key == 'email'}
    if not changes:
        raise HTTPException(422, 'Aucune modification')
    try:
        with store.connect() as connection:
            actor = lock_admin_actor(connection, request)
            previous = lock_admin_state(connection, user_id)
            next_role, next_active = changes.get('role', previous['role']), changes.get('active', previous['active'])
            if previous['role'] == 'admin' and previous['active'] and (next_role != 'admin' or not next_active):
                ensure_other_ready_admin(connection, user_id)
            identity = identity_values(previous, changes)
            connection.execute(
                'UPDATE auth_users SET display_name=%s,first_name=%s,last_name=%s,email=%s,role=%s,active=%s WHERE id=%s',
                (identity['display_name'], identity['first_name'], identity['last_name'], identity['email'], next_role, next_active, user_id),
            )
            if next_role != previous['role'] or next_active != previous['active']:
                revoke(connection, user_id)
            audit_event(connection, actor, 'user.updated', str(user_id),
                        {'previous_role': previous['role'], 'role': next_role, 'active': next_active})
            return get_user_view(connection, user_id)
    except psycopg.errors.UniqueViolation as error:
        raise identity_conflict(error) from None
