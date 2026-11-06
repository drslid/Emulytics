"""Administrator recovery and revocation preserve a usable administrative identity."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import UUID, uuid4

import pyotp
import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.access import audit_event, required_permission
from app.auth import PASSWORD_HASHER, SESSION_COOKIE, digest
from app.user_security_routes import revoke_sessions
from conftest import CONTROL_TOKEN
from test_authentication import auth_store, ORIGIN, PASSWORD
from test_self_security import enabled_session, password_payload
from test_user_roles import signed_in


def extra_session(store, user_id, *, expired=False):
    token = 'security-test-' + uuid4().hex
    with store.connect() as c:
        c.execute("INSERT INTO auth_sessions(token_hash,user_id,expires_at) VALUES(%s,%s,clock_timestamp()+%s*interval '1 hour')",
                  (digest(token), user_id, -1 if expired else 1))
    return token


def pending(store, user_id, token):
    with store.connect() as c:
        c.execute("INSERT INTO auth_pending_totp(user_id,session_hash,secret,expires_at) VALUES(%s,%s,%s,clock_timestamp()+interval '5 minutes')",
                  (user_id, digest(token), store.config.cipher.encrypt(pyotp.random_base32().encode()).decode()))


@pytest.mark.parametrize('role', ['builder', 'operator', 'viewer', 'auditor'])
def test_non_admin_cannot_use_direct_credential_actions(auth_store, app_module, role):
    _, client, _ = signed_in(auth_store, app_module, role)
    target = auth_store.create_user('target-' + role, PASSWORD, role='viewer')
    for action in ['reset-password', 'reset-2fa', 'force-password-change', 'revoke-sessions']:
        assert client.post(f"/console/users/{target['id']}/{action}", json={}).status_code == 403


def test_admin_uses_profile_for_own_credentials_and_can_revoke_own_sessions(auth_store, app_module):
    admin, client, token = signed_in(auth_store, app_module)
    for action in ['reset-password', 'reset-2fa', 'force-password-change']:
        response = client.post(f"/console/users/{admin['id']}/{action}", json={})
        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'self_security_required'
        assert auth_store.current_user(token)
    response = client.post(f"/console/users/{admin['id']}/revoke-sessions", json={})
    assert response.status_code == 200
    assert response.json()['revoked_sessions'] == 1
    assert response.json()['user']['active_sessions'] == 0
    assert 'Max-Age=0' in response.headers['set-cookie']
    assert client.get('/auth/me').status_code == 401


def test_reset_password_returns_once_preserves_factor_and_tracks_real_change(auth_store, app_module):
    _, admin, _ = signed_in(auth_store, app_module)
    user, victim, token = signed_in(auth_store, app_module, 'operator')
    with auth_store.connect() as c:
        before = c.execute('SELECT password_hash,totp_secret,password_changed_at FROM auth_users WHERE id=%s', (user['id'],)).fetchone()
    pending(auth_store, user['id'], token)
    result = admin.post(f"/console/users/{user['id']}/reset-password", json={})
    assert result.status_code == 200
    temporary = result.json()['temporary_password']
    assert len(temporary) >= 12
    assert result.json()['user']['password_change_required']
    assert result.json()['user']['totp_enabled']
    assert result.json()['user']['active_sessions'] == 0
    assert result.json()['user']['recovery_codes_remaining'] == 10
    assert victim.get('/devices').status_code == 401
    detail = admin.get(f"/console/users/{user['id']}")
    assert detail.status_code == 200 and temporary not in detail.text
    with auth_store.connect() as c:
        after = c.execute('SELECT password_hash,totp_secret,password_changed_at FROM auth_users WHERE id=%s', (user['id'],)).fetchone()
        assert after['totp_secret'] == before['totp_secret']
        assert PASSWORD_HASHER.verify(after['password_hash'], temporary)
        assert after['password_changed_at'] >= before['password_changed_at']
        assert c.execute('SELECT count(*) AS n FROM auth_pending_totp WHERE user_id=%s', (user['id'],)).fetchone()['n'] == 0
        assert temporary not in str(c.execute('SELECT * FROM audit_log').fetchall())
    assert victim.post('/auth/login', json={'username': user['username'], 'password': PASSWORD}).status_code == 401
    assert victim.post('/auth/login', json={'username': user['username'], 'password': temporary}).json()['step'] == 'change_password'


def test_force_change_revokes_but_does_not_replace_password_or_factor(auth_store, app_module):
    _, admin, _ = signed_in(auth_store, app_module)
    user, client, token = signed_in(auth_store, app_module, 'operator')
    with auth_store.connect() as c:
        before = c.execute('SELECT password_hash,totp_secret,password_changed_at FROM auth_users WHERE id=%s', (user['id'],)).fetchone()
    response = admin.post(f"/console/users/{user['id']}/force-password-change", json={})
    assert response.status_code == 200 and response.json()['password_change_required']
    assert response.json()['active_sessions'] == 0
    assert auth_store.current_user(token) is None
    with auth_store.connect() as c:
        after = c.execute('SELECT password_hash,totp_secret,password_changed_at FROM auth_users WHERE id=%s', (user['id'],)).fetchone()
        assert after == before
    assert client.post('/auth/login', json={'username': user['username'], 'password': PASSWORD}).json()['step'] == 'change_password'
    assert client.get('/devices').status_code == 401


def test_profile_password_change_updates_the_real_password_date(auth_store, app_module):
    user, secret, _, codes, client = enabled_session(auth_store, app_module)
    with auth_store.connect() as c:
        before = c.execute('SELECT password_changed_at FROM auth_users WHERE id=%s', (user['id'],)).fetchone()['password_changed_at']
    assert client.post('/console/account/password', json=password_payload(secret, auth_store, recovery_code=codes[0])).status_code == 200
    with auth_store.connect() as c:
        assert c.execute('SELECT password_changed_at FROM auth_users WHERE id=%s', (user['id'],)).fetchone()['password_changed_at'] > before


@pytest.mark.parametrize('password_gate', [False, True])
def test_reset_two_factor_clears_only_factor_and_retains_password_gate(auth_store, app_module, password_gate):
    _, admin, _ = signed_in(auth_store, app_module)
    user, _, token = signed_in(auth_store, app_module, 'operator')
    pending(auth_store, user['id'], token)
    with auth_store.connect() as c:
        c.execute('UPDATE auth_users SET password_change_required=%s WHERE id=%s', (password_gate, user['id']))
        previous = c.execute('SELECT password_hash,password_changed_at FROM auth_users WHERE id=%s', (user['id'],)).fetchone()
    response = admin.post(f"/console/users/{user['id']}/reset-2fa", json={})
    assert response.status_code == 200
    assert not response.json()['totp_enabled'] and response.json()['password_change_required'] == password_gate
    assert response.json()['recovery_codes_remaining'] == 0
    assert response.json()['active_sessions'] == 0
    with auth_store.connect() as c:
        after = c.execute('SELECT password_hash,password_changed_at,totp_secret,totp_last_counter FROM auth_users WHERE id=%s', (user['id'],)).fetchone()
        assert after['password_hash'] == previous['password_hash']
        assert after['password_changed_at'] == previous['password_changed_at']
        assert after['totp_secret'] is None and after['totp_last_counter'] == -1
        assert c.execute('SELECT count(*) AS n FROM auth_pending_totp WHERE user_id=%s', (user['id'],)).fetchone()['n'] == 0
    fresh = TestClient(app_module.app, base_url=ORIGIN, headers={'Origin': ORIGIN, 'X-Emulytix-Client': 'console'})
    assert fresh.post('/auth/login', json={'username': user['username'], 'password': PASSWORD}).json()['step'] == ('change_password' if password_gate else 'enroll')
    assert fresh.get('/devices').status_code == 401


def test_revocation_counts_only_live_sessions_and_cascades_pending_enrollment(auth_store, app_module):
    _, admin, _ = signed_in(auth_store, app_module)
    user, victim, _ = signed_in(auth_store, app_module, 'operator')
    second = extra_session(auth_store, user['id'])
    extra_session(auth_store, user['id'], expired=True)
    pending(auth_store, user['id'], second)
    auth_store.login(user['username'], PASSWORD, 'challenge-test')
    response = admin.post(f"/console/users/{user['id']}/revoke-sessions", json={})
    assert response.status_code == 200 and response.json()['revoked_sessions'] == 2
    assert response.json()['user']['active_sessions'] == 0
    assert response.json()['user']['totp_enabled']
    assert response.json()['user']['recovery_codes_remaining'] == 10
    assert victim.get('/auth/me').status_code == 401
    with auth_store.connect() as c:
        for table in ['auth_sessions', 'auth_challenges', 'auth_pending_totp']:
            assert c.execute(f'SELECT count(*) AS n FROM {table} WHERE user_id=%s', (user['id'],)).fetchone()['n'] == 0


def test_service_reset_cannot_remove_the_last_ready_admin(auth_store, app_module):
    admin, _, _ = signed_in(auth_store, app_module)
    auth_store.create_user('pending-admin', PASSWORD, role='admin')
    with TestClient(app_module.app, base_url=ORIGIN, headers={'Authorization': 'Bearer ' + CONTROL_TOKEN}) as service:
        for action in ['reset-password', 'reset-2fa', 'force-password-change']:
            response = service.post(f"/console/users/{admin['id']}/{action}", json={})
            assert response.status_code == 409
            assert response.json()['detail']['code'] == 'last_admin_required'


def test_revoked_actor_cannot_mutate_using_a_stale_middleware_identity(auth_store, app_module):
    actor, _, token = signed_in(auth_store, app_module)
    target, _, target_token = signed_in(auth_store, app_module, 'operator')
    request = Request({'type': 'http', 'method': 'POST', 'path': '/', 'headers': [(b'cookie', f'{SESSION_COOKIE}={token}'.encode())], 'state': {'auth_user': actor}})
    with auth_store.connect() as c:
        c.execute("UPDATE auth_users SET role='viewer' WHERE id=%s", (actor['id'],))
        c.execute('DELETE FROM auth_sessions WHERE user_id=%s', (actor['id'],))
    with pytest.raises(HTTPException) as failure:
        revoke_sessions(UUID(target['id']), request, Response(), auth_store)
    assert failure.value.status_code == 403
    assert auth_store.current_user(target_token)


def test_revocation_rollback_keeps_target_session(auth_store, app_module, monkeypatch):
    import app.user_security_routes as routes
    _, admin, _ = signed_in(auth_store, app_module)
    user, _, token = signed_in(auth_store, app_module, 'operator')
    def unavailable(*_args, **_kwargs):
        raise RuntimeError('injected audit failure')
    monkeypatch.setattr(routes, 'audit_event', unavailable)
    with pytest.raises(RuntimeError):
        admin.post(f"/console/users/{user['id']}/revoke-sessions", json={})
    assert auth_store.current_user(token)


def test_two_admins_cannot_reset_each_other_after_authorization_is_cached(auth_store, app_module, monkeypatch):
    import app.user_security_routes as routes
    first, one, _ = signed_in(auth_store, app_module, 'admin', 'admin-one')
    second, two, _ = signed_in(auth_store, app_module, 'admin', 'admin-two')
    authorized = Barrier(2)
    original = routes.lock_admin_actor

    def after_middleware(connection, request):
        authorized.wait(timeout=5)
        return original(connection, request)

    monkeypatch.setattr(routes, 'lock_admin_actor', after_middleware)
    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(one.post, f"/console/users/{second['id']}/reset-2fa", json={})
        right = pool.submit(two.post, f"/console/users/{first['id']}/reset-2fa", json={})
        assert sorted([left.result(timeout=10).status_code, right.result(timeout=10).status_code]) == [200, 403]
    with auth_store.connect() as c:
        assert c.execute("SELECT count(*) AS n FROM auth_users WHERE role='admin' AND active AND totp_enabled AND NOT password_change_required").fetchone()['n'] == 1


def test_target_logout_and_admin_revocation_do_not_deadlock(auth_store, app_module, monkeypatch):
    import app.user_security_routes as routes
    _, admin, _ = signed_in(auth_store, app_module)
    user, _, token = signed_in(auth_store, app_module, 'operator')
    session_deleted, target_locked = Event(), Event()
    original = routes.lock_admin_state

    def locked_target(connection, user_id):
        result = original(connection, user_id)
        target_locked.set()
        return result

    def concurrent_logout():
        with auth_store.connect() as c:
            removed = c.execute('DELETE FROM auth_sessions WHERE token_hash=%s RETURNING user_id', (digest(token),)).fetchone()
            session_deleted.set()
            assert target_locked.wait(timeout=5)
            audit_event(c, removed['user_id'], 'auth.session.closed', str(removed['user_id']))

    monkeypatch.setattr(routes, 'lock_admin_state', locked_target)
    with ThreadPoolExecutor(max_workers=2) as pool:
        logout = pool.submit(concurrent_logout)
        assert session_deleted.wait(timeout=5)
        result = pool.submit(admin.post, f"/console/users/{user['id']}/revoke-sessions", json={})
        response = result.result(timeout=10)
        logout.result(timeout=10)
    assert response.status_code == 200, response.text
    assert response.json()['revoked_sessions'] == 0
    assert auth_store.current_user(token) is None


def test_user_security_routes_declare_exact_methods():
    assert required_permission('PATCH', '/console/account/profile') == 'self'
    for action in ['reset-password', 'reset-2fa', 'force-password-change', 'revoke-sessions']:
        path = f'/console/users/example/{action}'
        assert required_permission('POST', path) == 'users.manage'
        assert required_permission('GET', path) is None
        assert required_permission('PATCH', path) is None
    assert required_permission('POST', '/console/users/example/unknown-action') is None
