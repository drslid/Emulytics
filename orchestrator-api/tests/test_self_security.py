"""Account operations use real PostgreSQL, MFA and cookie rotation without touching real accounts."""
from concurrent.futures import ThreadPoolExecutor
import json
from uuid import uuid4

import psycopg
import pyotp
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import PASSWORD_HASHER, digest
from app.self_security import Confirmation, PasswordChange, SelfSecurityStore
from test_authentication import auth_store, auth_client, current_code, ORIGIN, PASSWORD
from conftest import CONTROL_TOKEN

NEW_PASSWORD = 'A different personal password 918'


def enabled_session(store, app_module, role='viewer', username=None):
    user = store.create_user(username or 'profile-' + uuid4().hex[:10], PASSWORD, role=role)
    challenge, _ = store.login(user['username'], PASSWORD, 'setup')
    secret = store.enrollment(challenge)['secret']
    token, payload = store.verify(challenge, current_code(store, secret), 'setup')
    client = TestClient(app_module.app, base_url=ORIGIN, headers={'Origin': ORIGIN, 'X-Emulytix-Client': 'console'},
                        cookies={'emulytix_session': token})
    return user, secret, token, payload['recovery_codes'], client


def proof(secret, store, *, password=PASSWORD, recovery_code=None):
    return {'current_password': password, 'code': recovery_code or current_code(store, secret, 1),
            'recovery': recovery_code is not None}


def password_payload(secret, store, **kwargs):
    return {**proof(secret, store, **kwargs), 'new_password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD}


def raw_user(store, user):
    with store.connect() as connection:
        return connection.execute('SELECT * FROM auth_users WHERE id=%s', (user['id'],)).fetchone()


def other_session(store, user):
    token = uuid4().hex + uuid4().hex
    with store.connect() as connection:
        connection.execute("INSERT INTO auth_sessions(token_hash,user_id,expires_at) VALUES(%s,%s,clock_timestamp()+interval '8 hours')", (digest(token), user['id']))
    return token


@pytest.mark.parametrize('role', ['admin', 'builder', 'operator', 'viewer', 'auditor'])
def test_each_role_can_manage_only_its_own_account(auth_store, app_module, role):
    user, secret, old_token, codes, client = enabled_session(auth_store, app_module, role)
    assert client.get('/console/account/security').json() == {'two_factor_enabled': True, 'recovery_codes_remaining': 10, 'pending_enrollment_expires_at': None}
    payload = password_payload(secret, auth_store)
    assert client.post('/console/account/password', json={**payload, 'user_id': str(uuid4())}).status_code == 422
    response = client.post('/console/account/password', json=payload)
    assert response.status_code == 200 and response.json() == {'ok': True}
    assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']
    assert auth_store.current_user(old_token) is None
    assert client.get('/auth/me').json()['user']['id'] == user['id']
    assert client.get('/console/account/security').json()['recovery_codes_remaining'] == 10
    with pytest.raises(HTTPException) as old_password:
        auth_store.login(user['username'], PASSWORD, 'old-password')
    assert old_password.value.status_code == 401
    assert auth_store.login(user['username'], NEW_PASSWORD, 'new-password')[1] == 'verify'


def test_password_keeps_factor_codes_and_revokes_other_sessions_and_challenges(auth_store, app_module):
    user, secret, token, codes, client = enabled_session(auth_store, app_module)
    extra = other_session(auth_store, user)
    challenge, _ = auth_store.login(user['username'], PASSWORD, 'parallel-login')
    before = raw_user(auth_store, user)
    assert client.post('/console/account/password', json=password_payload(secret, auth_store, recovery_code=codes[0])).status_code == 200
    after = raw_user(auth_store, user)
    assert before['totp_secret'] == after['totp_secret'] and after['totp_enabled']
    assert auth_store.current_user(token) is None and auth_store.current_user(extra) is None
    with auth_store.connect() as connection:
        assert connection.execute('SELECT COUNT(*) AS n FROM auth_sessions WHERE user_id=%s', (user['id'],)).fetchone()['n'] == 1
        assert not connection.execute('SELECT 1 FROM auth_challenges WHERE token_hash=%s', (digest(challenge),)).fetchone()
        assert not connection.execute('SELECT 1 FROM auth_recovery_codes WHERE user_id=%s AND code_hash=%s', (user['id'], digest(codes[0]))).fetchone()
        assert connection.execute('SELECT COUNT(*) AS n FROM auth_recovery_codes WHERE user_id=%s', (user['id'],)).fetchone()['n'] == 9


def test_failed_confirmation_changes_nothing_and_never_logs_secrets(auth_store, app_module):
    user, secret, token, codes, client = enabled_session(auth_store, app_module)
    before = raw_user(auth_store, user)
    bad = password_payload(secret, auth_store, password='a wrong current password')
    response = client.post('/console/account/password', json=bad)
    assert response.status_code == 403 and client.get('/auth/me').status_code == 200
    # The code just accepted at login cannot be replayed for a sensitive action.
    replayed = {**password_payload(secret, auth_store), 'code': current_code(auth_store, secret)}
    assert client.post('/console/account/password', json=replayed).status_code == 403
    assert raw_user(auth_store, user)['password_hash'] == before['password_hash']
    assert auth_store.current_user(token)
    for invalid in [{**bad, 'new_password': 'short'}, {**bad, 'code': '123'}, {**bad, 'new_password': '\ud800' * 12}, {**bad, 'new_password': NEW_PASSWORD, 'confirm_password': PASSWORD}]:
        result = client.post('/console/account/password', content=json.dumps(invalid), headers={'Content-Type':'application/json'})
        assert result.status_code == 422
        assert 'a wrong current password' not in result.text and NEW_PASSWORD not in result.text
    with auth_store.connect() as connection:
        logs = str(connection.execute('SELECT * FROM audit_log').fetchall())
    assert PASSWORD not in logs and secret not in logs and codes[0] not in logs


def test_last_backup_preserved_for_factor_replacement_and_regeneration_needs_totp(auth_store, app_module):
    user, secret, token, codes, client = enabled_session(auth_store, app_module)
    with auth_store.connect() as connection:
        connection.execute('DELETE FROM auth_recovery_codes WHERE user_id=%s AND code_hash<>%s', (user['id'], digest(codes[0])))
    assert client.post('/console/account/password', json=password_payload(secret, auth_store, recovery_code=codes[0])).status_code == 403
    assert client.post('/console/account/recovery-codes', json=proof(secret, auth_store, recovery_code=codes[0])).status_code == 403
    assert client.get('/console/account/security').json()['recovery_codes_remaining'] == 1
    assert client.post('/console/account/two-factor/start', json=proof(secret, auth_store, recovery_code=codes[0])).status_code == 200
    assert client.get('/console/account/security').json()['recovery_codes_remaining'] == 0
    assert client.get('/console/account/two-factor/enrollment').status_code == 200


def test_replacement_secret_is_session_bound_encrypted_and_does_not_disable_current_factor(auth_store, app_module):
    user, old_secret, token, codes, client = enabled_session(auth_store, app_module)
    extra = other_session(auth_store, user)
    other = TestClient(app_module.app, base_url=ORIGIN, cookies={'emulytix_session': extra})
    assert client.get('/console/account/two-factor/enrollment').status_code == 403
    before = raw_user(auth_store, user)
    start = client.post('/console/account/two-factor/start', json=proof(old_secret, auth_store, recovery_code=codes[0]))
    assert start.status_code == 200 and start.json()['expires_at']
    assert 'secret' not in start.json()
    data = client.get('/console/account/two-factor/enrollment').json()
    assert data['secret'] != old_secret and data['otpauth_uri'].startswith('otpauth://totp/Emulytix:')
    assert '<svg' in client.get('/console/account/two-factor/enrollment/qr').text
    assert other.get('/console/account/two-factor/enrollment').status_code == 403
    assert other.get('/console/account/security').json()['pending_enrollment_expires_at'] is None
    after = raw_user(auth_store, user)
    assert before['totp_secret'] == after['totp_secret'] and after['totp_enabled']
    with auth_store.connect() as connection:
        stored = connection.execute('SELECT * FROM auth_pending_totp WHERE user_id=%s', (user['id'],)).fetchone()
        assert data['secret'] not in stored['secret'] and stored['session_hash'] == digest(token)
    # Old app continues to authenticate while the replacement is only pending.
    challenge, _ = auth_store.login(user['username'], PASSWORD, 'old-app')
    assert auth_store.verify(challenge, current_code(auth_store, old_secret, 1), 'old-app')[0]


def test_cancel_and_expiry_keep_old_factor_usable(auth_store, app_module):
    user, secret, token, codes, client = enabled_session(auth_store, app_module)
    before = raw_user(auth_store, user)
    assert client.post('/console/account/two-factor/start', json=proof(secret, auth_store, recovery_code=codes[0])).status_code == 200
    assert client.request('DELETE', '/console/account/two-factor/enrollment', json={}).status_code == 200
    assert client.get('/console/account/two-factor/enrollment').status_code == 403
    assert raw_user(auth_store, user)['totp_secret'] == before['totp_secret']
    assert client.post('/console/account/two-factor/start', json=proof(secret, auth_store, recovery_code=codes[1])).status_code == 200
    with auth_store.connect() as connection:
        connection.execute("UPDATE auth_pending_totp SET expires_at=clock_timestamp()-interval '1 second' WHERE user_id=%s", (user['id'],))
    assert client.get('/console/account/two-factor/enrollment').status_code == 403
    assert client.post('/console/account/two-factor/confirm', json={'code': current_code(auth_store, secret, 1)}).status_code == 403
    assert auth_store.current_user(token)
    challenge, _ = auth_store.login(user['username'], PASSWORD, 'old-valid')
    assert auth_store.verify(challenge, current_code(auth_store, secret, 1), 'old-valid')[0]


def test_confirm_changes_factor_codes_and_sessions_atomically(auth_store, app_module):
    user, old_secret, token, old_codes, client = enabled_session(auth_store, app_module)
    extra = other_session(auth_store, user)
    assert client.post('/console/account/two-factor/start', json=proof(old_secret, auth_store, recovery_code=old_codes[0])).status_code == 200
    new_secret = client.get('/console/account/two-factor/enrollment').json()['secret']
    bad = current_code(auth_store, old_secret, 1)
    if bad != current_code(auth_store, new_secret):
        assert client.post('/console/account/two-factor/confirm', json={'code': bad}).status_code == 403
    result = client.post('/console/account/two-factor/confirm', json={'code': current_code(auth_store, new_secret)})
    assert result.status_code == 200
    new_codes = result.json()['recovery_codes']
    assert len(set(new_codes)) == 10 and not set(new_codes) & set(old_codes)
    assert auth_store.current_user(token) is None and auth_store.current_user(extra) is None
    assert client.get('/auth/me').status_code == 200
    assert client.get('/console/account/two-factor/enrollment').status_code == 403
    after = raw_user(auth_store, user)
    assert auth_store.config.cipher.decrypt(after['totp_secret'].encode()).decode() == new_secret
    with auth_store.connect() as connection:
        stored = connection.execute('SELECT code_hash FROM auth_recovery_codes WHERE user_id=%s', (user['id'],)).fetchall()
        assert {r['code_hash'] for r in stored} == {digest(c) for c in new_codes}
        assert not connection.execute('SELECT 1 FROM auth_pending_totp WHERE user_id=%s', (user['id'],)).fetchone()
    challenge, _ = auth_store.login(user['username'], PASSWORD, 'after-change')
    with pytest.raises(HTTPException):
        auth_store.verify(challenge, old_codes[1], 'after-change', recovery=True)
    assert auth_store.verify(challenge, current_code(auth_store, new_secret, 1), 'after-change')[0]


def test_recovery_regeneration_requires_new_totp_and_rotates_the_session(auth_store, app_module):
    user, secret, token, codes, client = enabled_session(auth_store, app_module)
    extra = other_session(auth_store, user)
    response = client.post('/console/account/recovery-codes', json=proof(secret, auth_store))
    assert response.status_code == 200
    regenerated = response.json()['recovery_codes']
    assert len(set(regenerated)) == 10
    assert auth_store.current_user(token) is None and auth_store.current_user(extra) is None
    assert client.get('/auth/me').status_code == 200
    assert client.get('/console/account/security').json()['recovery_codes_remaining'] == 10
    with auth_store.connect() as connection:
        stored = {row['code_hash'] for row in connection.execute('SELECT code_hash FROM auth_recovery_codes WHERE user_id=%s', (user['id'],))}
        assert stored == {digest(c) for c in regenerated} and digest(codes[0]) not in stored


def test_no_cookie_service_bearer_csrf_and_cross_user_payloads_cannot_manage_credentials(auth_store, app_module):
    user, secret, token, codes, client = enabled_session(auth_store, app_module)
    bare = TestClient(app_module.app, base_url=ORIGIN)
    assert bare.get('/console/account/security').status_code == 401
    assert bare.post('/console/account/password', json=password_payload(secret, auth_store), headers={'Authorization': 'Bearer ' + CONTROL_TOKEN}).status_code == 403
    assert client.post('/console/account/password', json=password_payload(secret, auth_store), headers={'Authorization': 'Bearer ' + CONTROL_TOKEN, 'Origin': 'https://evil.test'}).status_code == 403
    assert client.post('/console/account/password', json=password_payload(secret, auth_store), headers={'Origin': 'https://evil.test'}).status_code == 403
    assert client.post('/console/account/two-factor/disable', json={}).status_code == 403
    assert client.get('/console/account/security').status_code == 200
    assert auth_store.current_user(token)


def test_account_limit_is_committed_when_confirmation_fails(auth_store, app_module):
    user, secret, token, codes, client = enabled_session(auth_store, app_module)
    bad = proof(secret, auth_store, password='incorrect current password')
    for _ in range(10):
        assert client.post('/console/account/two-factor/start', json=bad).status_code == 403
    assert client.post('/console/account/two-factor/start', json=bad).status_code == 429
    assert client.get('/console/account/security').status_code == 200


def test_concurrent_confirm_cannot_activate_twice(auth_store, app_module):
    user, secret, token, codes, client = enabled_session(auth_store, app_module)
    assert client.post('/console/account/two-factor/start', json=proof(secret, auth_store, recovery_code=codes[0])).status_code == 200
    new_secret = client.get('/console/account/two-factor/enrollment').json()['secret']
    store = SelfSecurityStore(auth_store.config)
    def confirm():
        try:
            return store.confirm_replacement(token, current_code(auth_store, new_secret), 'race')
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: confirm(), range(2)))
    assert len([result for result in results if isinstance(result, tuple)]) == 1
    assert 401 in results
    with auth_store.connect() as connection:
        assert connection.execute('SELECT COUNT(*) AS n FROM auth_sessions WHERE user_id=%s', (user['id'],)).fetchone()['n'] == 1
        assert connection.execute("SELECT COUNT(*) AS n FROM audit_log WHERE action='account.two_factor.changed'").fetchone()['n'] == 1


def test_password_mutation_rolls_back_when_audit_commit_fails(auth_store, app_module, monkeypatch):
    user, secret, token, codes, client = enabled_session(auth_store, app_module)
    import app.self_security as module
    before = raw_user(auth_store, user)
    def fail(*args, **kwargs):
        raise RuntimeError('fault after credential updates')
    monkeypatch.setattr(module, 'audit_event', fail)
    payload = PasswordChange(**password_payload(secret, auth_store, recovery_code=codes[0]))
    with pytest.raises(RuntimeError):
        SelfSecurityStore(auth_store.config).change_own_password(token, payload, 'fault')
    assert raw_user(auth_store, user)['password_hash'] == before['password_hash']
    assert auth_store.current_user(token)
    with auth_store.connect() as connection:
        assert connection.execute('SELECT 1 FROM auth_recovery_codes WHERE user_id=%s AND code_hash=%s', (user['id'], digest(codes[0]))).fetchone()


def test_existing_multibyte_password_over_1024_bytes_remains_manageable(auth_store, app_module):
    wide_password = '🔒' * 300
    user = auth_store.create_user('unicode-profile', wide_password, role='viewer')
    challenge, _ = auth_store.login(user['username'], wide_password, 'unicode')
    secret = auth_store.enrollment(challenge)['secret']
    token, _ = auth_store.verify(challenge, current_code(auth_store, secret), 'unicode')
    client = TestClient(app_module.app, base_url=ORIGIN, headers={'Origin': ORIGIN, 'X-Emulytix-Client': 'console'}, cookies={'emulytix_session': token})
    result = client.post('/console/account/password', json=password_payload(secret, auth_store, password=wide_password))
    assert result.status_code == 200
    assert PASSWORD_HASHER.verify(raw_user(auth_store, user)['password_hash'], NEW_PASSWORD)


def test_session_revoked_after_initial_check_cannot_change_credentials(auth_store, app_module, monkeypatch):
    user, secret, token, codes, _ = enabled_session(auth_store, app_module)
    store = SelfSecurityStore(auth_store.config)
    original = store.limit
    def revoke_after_limit(*args, **kwargs):
        original(*args, **kwargs)
        with auth_store.connect() as connection:
            connection.execute('DELETE FROM auth_sessions WHERE token_hash=%s', (digest(token),))
    monkeypatch.setattr(store, 'limit', revoke_after_limit)
    payload = PasswordChange(**password_payload(secret, auth_store, recovery_code=codes[0]))
    before = raw_user(auth_store, user)
    with pytest.raises(HTTPException) as rejected:
        store.change_own_password(token, payload, 'revoked')
    assert rejected.value.status_code == 401
    assert raw_user(auth_store, user)['password_hash'] == before['password_hash']
    with auth_store.connect() as connection:
        assert connection.execute('SELECT 1 FROM auth_recovery_codes WHERE user_id=%s AND code_hash=%s', (user['id'], digest(codes[0]))).fetchone()


def test_replacement_commit_rolls_back_secret_codes_session_and_pending(auth_store, app_module, monkeypatch):
    user, secret, token, codes, client = enabled_session(auth_store, app_module)
    assert client.post('/console/account/two-factor/start', json=proof(secret, auth_store, recovery_code=codes[0])).status_code == 200
    pending_secret = client.get('/console/account/two-factor/enrollment').json()['secret']
    before = raw_user(auth_store, user)
    import app.self_security as module
    def fail(*args, **kwargs):
        raise RuntimeError('factor commit fault')
    monkeypatch.setattr(module, 'audit_event', fail)
    with pytest.raises(RuntimeError):
        SelfSecurityStore(auth_store.config).confirm_replacement(token, current_code(auth_store, pending_secret), 'fault')
    assert raw_user(auth_store, user)['totp_secret'] == before['totp_secret']
    assert auth_store.current_user(token)
    assert client.get('/console/account/two-factor/enrollment').json()['secret'] == pending_secret
    with auth_store.connect() as connection:
        assert connection.execute('SELECT COUNT(*) AS n FROM auth_recovery_codes WHERE user_id=%s', (user['id'],)).fetchone()['n'] == 9


def test_concurrent_logout_and_profile_read_do_not_deadlock(auth_store, app_module, monkeypatch):
    from contextlib import contextmanager
    from threading import Event
    import app.auth as auth_module
    user, secret, token, codes, client = enabled_session(auth_store, app_module)
    deleted, user_locked = Event(), Event()
    original_audit = auth_module.audit_event
    def wait_for_profile_lock(connection, *args, **kwargs):
        deleted.set()
        assert user_locked.wait(4)
        return original_audit(connection, *args, **kwargs)
    monkeypatch.setattr(auth_module, 'audit_event', wait_for_profile_lock)
    store = SelfSecurityStore(auth_store.config)
    original_connect = store.connect
    class ConnectionProxy:
        def __init__(self, connection):
            self.connection = connection
        def execute(self, query, *args, **kwargs):
            result = self.connection.execute(query, *args, **kwargs)
            if query.startswith('SELECT * FROM auth_users'):
                user_locked.set()
            return result
    @contextmanager
    def connect():
        with original_connect() as connection:
            yield ConnectionProxy(connection)
    monkeypatch.setattr(store, 'connect', connect)
    def logout():
        auth_store.logout(token, None)
        return 'logout_ok'
    def read_profile():
        assert deleted.wait(4)
        try:
            store.status(token)
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(logout), pool.submit(read_profile)
        assert first.result() == 'logout_ok'
        assert second.result() == 401
