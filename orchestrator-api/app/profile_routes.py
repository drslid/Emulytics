"""Cookie-bound edits to the current user's contact identity."""
import psycopg
from fastapi import APIRouter, HTTPException, Request

from .access import audit_event
from .auth import AuthStore, SESSION_COOKIE
from .auth_routes import AuthRoute
from .self_security import Store
from .user_identity import ProfilePatch, identity_conflict, identity_values


router = APIRouter(prefix='/console/account/profile', tags=['My profile'], route_class=AuthRoute)


@router.get('')
def profile(request: Request, store: Store):
    with store.connect() as connection:
        user = store._session_user(connection, request.cookies.get(SESSION_COOKIE))
        return {'user': AuthStore.public_user(user)}


@router.patch('')
def update_profile(payload: ProfilePatch, request: Request, store: Store):
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, 'Aucune modification')
    try:
        with store.connect() as connection:
            user = store._session_user(connection, request.cookies.get(SESSION_COOKIE))
            identity = identity_values(user, changes)
            row = connection.execute(
                'UPDATE auth_users SET first_name=%s,last_name=%s,email=%s,display_name=%s WHERE id=%s RETURNING *',
                (identity['first_name'], identity['last_name'], identity['email'], identity['display_name'], user['id']),
            ).fetchone()
            store._live_session(connection, user)
            audit_event(connection, user['id'], 'account.profile.updated', str(user['id']))
            return {'user': AuthStore.public_user(row)}
    except psycopg.errors.UniqueViolation as error:
        raise identity_conflict(error) from None
