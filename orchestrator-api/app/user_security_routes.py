"""Administrator credential actions; self-service stays in the protected profile flow."""
import secrets
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from .access import audit_event
from .admin_guard import lock_admin_actor
from .auth import PASSWORD_HASHER, SESSION_COOKIE
from .auth_routes import AuthRoute, Store, clear_challenge
from .user_routes import ensure_other_ready_admin, get_user_view, lock_admin_state, revoke

router = APIRouter(prefix='/console/users', tags=['User security administration'], route_class=AuthRoute)


def credential_target(connection, request, user_id):
    actor = lock_admin_actor(connection, request)
    target = lock_admin_state(connection, user_id)
    if actor == target['id']:
        raise HTTPException(409, {'code': 'self_security_required'})
    if target['role'] == 'admin' and target['active'] and target['totp_enabled'] and not target['password_change_required']:
        ensure_other_ready_admin(connection, user_id)
    return actor, target


@router.post('/{user_id}/reset-password')
def reset_password(user_id: UUID, request: Request, store: Store):
    password = secrets.token_urlsafe(24)
    password_hash = PASSWORD_HASHER.hash(password)
    with store.connect() as connection:
        actor, _ = credential_target(connection, request, user_id)
        connection.execute(
            'UPDATE auth_users SET password_hash=%s,password_change_required=true,password_changed_at=clock_timestamp() WHERE id=%s',
            (password_hash, user_id),
        )
        revoke(connection, user_id)
        audit_event(connection, actor, 'user.password.reset', str(user_id))
        user = get_user_view(connection, user_id)
    return {'user': user, 'temporary_password': password}


@router.post('/{user_id}/reset-2fa')
def reset_two_factor(user_id: UUID, request: Request, store: Store):
    with store.connect() as connection:
        actor, _ = credential_target(connection, request, user_id)
        revoke(connection, user_id)
        connection.execute('DELETE FROM auth_recovery_codes WHERE user_id=%s', (user_id,))
        connection.execute(
            'UPDATE auth_users SET totp_secret=NULL,totp_enabled=false,totp_last_counter=-1 WHERE id=%s', (user_id,),
        )
        audit_event(connection, actor, 'user.two_factor.reset', str(user_id))
        return get_user_view(connection, user_id)


@router.post('/{user_id}/force-password-change')
def force_password_change(user_id: UUID, request: Request, store: Store):
    with store.connect() as connection:
        actor, _ = credential_target(connection, request, user_id)
        connection.execute('UPDATE auth_users SET password_change_required=true WHERE id=%s', (user_id,))
        revoke(connection, user_id)
        audit_event(connection, actor, 'user.password.change_required', str(user_id))
        return get_user_view(connection, user_id)


@router.post('/{user_id}/revoke-sessions')
def revoke_sessions(user_id: UUID, request: Request, response: Response, store: Store):
    with store.connect() as connection:
        actor = lock_admin_actor(connection, request)
        lock_admin_state(connection, user_id)
        revoked = connection.execute(
            'DELETE FROM auth_sessions WHERE user_id=%s AND expires_at>clock_timestamp() RETURNING token_hash', (user_id,),
        ).fetchall()
        # Remove expired sessions too; a pending enrollment cascades with its session.
        revoke(connection, user_id)
        audit_event(connection, actor, 'user.sessions.revoked', str(user_id))
        user = get_user_view(connection, user_id)
    if actor == user_id:
        response.delete_cookie(SESSION_COOKIE, path='/', httponly=True, secure=store.config.secure, samesite='strict')
        clear_challenge(response, store)
    return {'user': user, 'revoked_sessions': len(revoked)}
