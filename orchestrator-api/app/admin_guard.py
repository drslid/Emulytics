"""Revalidate an administrator at the transaction boundary, before locking a target."""
from fastapi import HTTPException, Request

from .auth import SESSION_COOKIE, digest, valid_control_token


def lock_admin_actor(connection, request: Request):
    # All administrator mutations share this order, including cross-admin changes.
    connection.execute('SELECT singleton FROM auth_installation WHERE singleton FOR UPDATE').fetchone()
    actor = getattr(request.state, 'auth_user', None)
    if actor is None:
        if valid_control_token(request):
            return None
        raise HTTPException(401, 'Connexion requise')
    user = connection.execute(
        'SELECT id,role,active,totp_enabled,password_change_required FROM auth_users WHERE id=%s FOR NO KEY UPDATE',
        (actor['id'],),
    ).fetchone()
    if not user or user['role'] != 'admin' or not user['active'] or not user['totp_enabled'] or user['password_change_required']:
        raise HTTPException(403, 'Droits administrateur requis')
    token = request.cookies.get(SESSION_COOKIE)
    if not token or len(token) > 128:
        raise HTTPException(401, 'Connexion requise')
    session = connection.execute(
        'SELECT user_id FROM auth_sessions WHERE token_hash=%s AND expires_at>clock_timestamp() FOR UPDATE',
        (digest(token),),
    ).fetchone()
    if not session or session['user_id'] != user['id']:
        raise HTTPException(401, 'Connexion requise')
    return user['id']
