"""Permission checks use real PostgreSQL sessions; clients cannot grant their own role."""

from concurrent.futures import ThreadPoolExecutor
import json

import pytest
from fastapi.testclient import TestClient

from app.access import ROLE_PERMISSIONS, audit_event, normalize_username, required_permission
from app.auth import PASSWORD_HASHER
from test_authentication import auth_client, auth_store, current_code, ORIGIN, PASSWORD


def signed_in(auth_store, app_module, role='admin', username=None):
    username = username or f'test-{role}'
    user = auth_store.create_user(username, PASSWORD, role=role)
    token, _ = auth_store.login(username, PASSWORD, username)
    secret = auth_store.enrollment(token)['secret']
    token, _ = auth_store.verify(token, current_code(auth_store, secret), username)
    client = TestClient(app_module.app, base_url=ORIGIN,
                        headers={'Origin': ORIGIN, 'X-Emulytix-Client': 'console'},
                        cookies={'emulytix_session': token})
    return user, client, token


@pytest.mark.parametrize('role', ['admin', 'builder', 'operator', 'viewer', 'auditor'])
def test_every_role_enforced_on_direct_mutations(auth_store, app_module, role):
    user, client, _ = signed_in(auth_store, app_module, role)
    response = client.get('/auth/me')
    assert response.status_code == 200
    assert response.json()['user']['role'] == role
    assert set(response.json()['user']['permissions']) == ROLE_PERMISSIONS[role]
    assert client.get('/devices').status_code == 200
    device = client.post('/devices', json={'device_id': f'phone-{role}', 'host_id': 'host-1', 'serial': f'Serial-{role}', 'kind': 'physical'})
    assert device.status_code == (201 if 'devices.write' in ROLE_PERMISSIONS[role] else 403)
    workflows = client.post('/workflows', json={})
    assert workflows.status_code == (422 if 'workflows.publish' in ROLE_PERMISSIONS[role] else 403)
    runs = client.post('/runs', json={})
    assert runs.status_code == (422 if 'runs.execute' in ROLE_PERMISSIONS[role] else 403)
    users = client.get('/console/users')
    assert users.status_code == (200 if role == 'admin' else 403)
    logs = client.get('/console/logs')
    # Monitoring module is root-owned; until it exists middleware still protects its path.
    if 'logs.read' in ROLE_PERMISSIONS[role]:
        assert logs.status_code != 403
    else:
        assert logs.status_code == 403
    assert client.get('/sessions').status_code == 403
    assert client.get('/unknown-protected-route').status_code == 403


def test_create_normalizes_name_and_returns_secret_once_with_required_onboarding(auth_store, app_module):
    admin, client, _ = signed_in(auth_store, app_module)
    result = client.post('/console/users', json={'username': ' Équipe     Paris ', 'role': 'builder'})
    assert result.status_code == 201, result.text
    created = result.json()
    user, temporary = created['user'], created['temporary_password']
    assert user['username'] == 'equipe-paris' and user['display_name'] == 'Équipe Paris'
    assert user['role'] == 'builder' and user['password_change_required'] and not user['totp_enabled']
    assert temporary not in client.get('/console/users').text
    assert 'password_hash' not in client.get('/console/users').text
    with auth_store.connect() as connection:
        row = connection.execute('SELECT * FROM auth_users WHERE id=%s', (user['id'],)).fetchone()
        assert PASSWORD_HASHER.verify(row['password_hash'], temporary)
        logs = connection.execute('SELECT * FROM audit_log').fetchall()
        assert temporary not in str(logs) and row['password_hash'] not in str(logs)
    fresh = TestClient(app_module.app, base_url=ORIGIN, headers={'Origin': ORIGIN, 'X-Emulytix-Client': 'console'})
    assert fresh.post('/auth/login', json={'username': ' Équipe   Paris ', 'password': temporary}).json() == {'step': 'change_password'}
    assert fresh.get('/devices').status_code == 401
    assert fresh.get('/auth/enrollment').status_code == 403
    assert fresh.post('/auth/change-password', json={'password': PASSWORD, 'confirm_password': PASSWORD}).json() == {'step': 'enroll'}
    secret = fresh.get('/auth/enrollment').json()['secret']
    assert fresh.post('/auth/verify', json={'code': current_code(auth_store, secret)}).json()['user']['role'] == 'builder'
    assert fresh.get('/devices').status_code == 200
    assert fresh.get('/console/users').status_code == 403
    assert client.post('/console/users', json={'username': 'Équipe Paris', 'role': 'viewer'}).status_code == 409
    renamed = client.patch(f"/console/users/{user['id']}", json={'display_name': ' Équipe    Lyon '})
    assert renamed.status_code == 200 and renamed.json()['display_name'] == 'Équipe Lyon'
    assert renamed.json()['username'] == 'equipe-paris'


def test_nonlatin_username_normalization_stable_and_unicode_validation(auth_store, app_module):
    _, client, _ = signed_in(auth_store, app_module)
    result = client.post('/console/users', json={'username': '北京 用户', 'role': 'viewer'})
    assert result.status_code == 201
    assert result.json()['user']['username'] == normalize_username('北京 用户')
    token, step = auth_store.login('北京 用户', result.json()['temporary_password'], 'test')
    assert step == 'change_password'
    for name in ['!!!', '   ', '\ud800']:
        assert client.post('/console/users', content=json.dumps({'username': name, 'role': 'viewer'}), headers={'Content-Type': 'application/json'}).status_code == 422


def test_last_active_admin_guard_survives_concurrent_demotions(auth_store, app_module):
    first, one, _ = signed_in(auth_store, app_module, 'admin', 'admin-one')
    second, two, _ = signed_in(auth_store, app_module, 'admin', 'admin-two')
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(one.patch, f"/console/users/{first['id']}", json={'role': 'viewer'})
        b = pool.submit(two.patch, f"/console/users/{second['id']}", json={'active': False})
        assert sorted([a.result().status_code, b.result().status_code]) == [200, 409]
    with auth_store.connect() as connection:
        assert connection.execute("SELECT count(*) AS n FROM auth_users WHERE role='admin' AND active").fetchone()['n'] == 1


def test_role_change_and_disabling_revoke_sessions_and_pending_challenges(auth_store, app_module):
    _, admin, _ = signed_in(auth_store, app_module)
    user, client, token = signed_in(auth_store, app_module, 'builder')
    challenge, _ = auth_store.login(user['username'], PASSWORD, 'test')
    updated = admin.patch(f"/console/users/{user['id']}", json={'role': 'viewer'})
    assert updated.status_code == 200 and updated.json()['role'] == 'viewer'
    assert client.get('/devices').status_code == 401
    assert auth_store.current_user(token) is None
    assert admin.patch(f"/console/users/{user['id']}", json={'active': False}).status_code == 200
    assert client.post('/auth/login', json={'username': user['username'], 'password': PASSWORD}).status_code == 401
    client.cookies.set('emulytix_challenge', challenge)
    assert client.get('/auth/enrollment').status_code == 401


def test_reset_credentials_revokes_session_and_preserves_required_password_gate(auth_store, app_module):
    _, admin, _ = signed_in(auth_store, app_module)
    user, client, token = signed_in(auth_store, app_module, 'operator')
    result = admin.post(f"/console/users/{user['id']}/reset-password", json={})
    assert result.status_code == 200
    assert client.get('/devices').status_code == 401
    assert result.json()['user']['totp_enabled'] and result.json()['user']['password_change_required']
    assert client.post('/auth/login', json={'username': user['username'], 'password': result.json()['temporary_password']}).json() == {'step': 'change_password'}
    assert admin.post(f"/console/users/{user['id']}/reset-2fa", json={}).status_code == 200
    with auth_store.connect() as connection:
        row = connection.execute('SELECT * FROM auth_users WHERE id=%s', (user['id'],)).fetchone()
        assert row['password_change_required'] and not row['totp_enabled'] and row['totp_secret'] is None
        assert connection.execute('SELECT count(*) AS n FROM auth_sessions WHERE user_id=%s', (user['id'],)).fetchone()['n'] == 0


def test_audit_allowlist_discards_secret_fields_and_user_validation_never_echoes(auth_store, app_module):
    user, client, _ = signed_in(auth_store, app_module)
    sentinel = 'NEVER-IN-AUDIT-password-or-token'
    with auth_store.connect() as connection:
        audit_event(connection, user['id'], 'review.test', metadata={'password': sentinel, 'token': sentinel, 'body': sentinel, 'role': 'viewer'})
        row = connection.execute("SELECT * FROM audit_log WHERE action='review.test'").fetchone()
        assert row['metadata'] == {'role': 'viewer'}
    response = client.post('/console/users', json={'username': 'new-user', 'role': 'root', 'password': sentinel})
    assert response.status_code == 422 and sentinel not in response.text
    assert required_permission('POST', '/console/schedules/preview') == 'schedules.read'
