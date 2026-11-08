"""Personal secrets never become service credentials or bypass the owner's current role."""
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from app.api_key_store import APIKeyStore, KeyCreation
from app.auth import digest
from test_authentication import auth_store
from test_self_security import enabled_session, proof
from app.auth_routes import AuthMiddleware
from app.personal_api_routes import router, account_router
from app.run_models import DeviceRegistration, WorkflowRegistration
from app.run_store import RunStore
from test_authentication import ORIGIN
import hashlib


@pytest.fixture
def api_app():
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(router)
    app.include_router(account_router)
    return app


def key_payload(secret, store, scopes=None, **values):
    return KeyCreation(**{**proof(secret, store), 'request_id': str(uuid4()), 'name': '  Local   MCP  ',
                          'scopes': scopes or ['devices.read', 'workflows.read', 'runs.read'], **values})


def issue(store, app_module, role='builder', scopes=None):
    user, secret, session, codes, client = enabled_session(store, app_module, role)
    keys = APIKeyStore(store.config)
    payload = key_payload(secret, store, scopes)
    return keys, user, session, payload, keys.create_key(session, payload, 'test')


def test_key_secret_shown_once_hashed_and_personal(auth_store, app_module):
    keys, user, session, payload, created = issue(auth_store, app_module)
    assert created['shown_once'] and created['secret'].startswith('emk_')
    assert created['key']['name'] == 'Local MCP'
    listed = keys.list_keys(session)
    assert listed['total'] == 1 and 'secret' not in str(listed)
    assert created['secret'] not in str(listed)
    with keys.connect() as connection:
        row = connection.execute('SELECT * FROM personal_api_keys').fetchone()
        assert row['token_hash'] == digest(created['secret']) and created['secret'] not in str(row)
        logs = str(connection.execute('SELECT * FROM audit_log').fetchall())
        assert created['secret'] not in logs and payload.current_password not in logs
    principal = keys.authenticate_key('Bearer ' + created['secret'])
    assert principal['user']['id'] == user['id'] and principal['scopes'] == created['key']['scopes']
    with pytest.raises(HTTPException) as duplicate:
        keys.create_key(session, payload, 'test')
    assert duplicate.value.status_code == 409
    other, _, other_session, _, _ = enabled_session(auth_store, app_module, 'admin')
    assert keys.list_keys(other_session)['items'] == []
    with pytest.raises(HTTPException) as forbidden:
        keys.revoke_key(other_session, created['key']['id'])
    assert forbidden.value.status_code == 404
    assert keys.revoke_key(session, created['key']['id']) == {'ok': True}
    assert keys.revoke_key(session, created['key']['id']) == {'ok': True}
    with pytest.raises(HTTPException) as revoked:
        keys.authenticate_key('Bearer ' + created['secret'])
    assert revoked.value.status_code == 401


@pytest.mark.parametrize('change', ["role='viewer'", 'active=false', 'totp_enabled=false',
                                   'password_change_required=true', "password_hash=password_hash||'x'",
                                   "totp_secret=totp_secret||'x'"])
def test_access_changes_permanently_revoke_keys(auth_store, app_module, change):
    keys, user, session, payload, created = issue(auth_store, app_module)
    with keys.connect() as connection:
        connection.execute('UPDATE auth_users SET ' + change + ' WHERE id=%s', (user['id'],))
        assert connection.execute('SELECT revoked_at FROM personal_api_keys WHERE id=%s', (created['key']['id'],)).fetchone()['revoked_at']
    with pytest.raises(HTTPException) as rejected:
        keys.authenticate_key('Bearer ' + created['secret'])
    assert rejected.value.status_code == 401


def test_key_scope_expiration_and_fresh_factor_required(auth_store, app_module):
    user, secret, session, codes, client = enabled_session(auth_store, app_module, 'viewer')
    keys = APIKeyStore(auth_store.config)
    with pytest.raises(HTTPException) as excessive:
        keys.create_key(session, key_payload(secret, auth_store, ['runs.execute']), 'test')
    assert excessive.value.status_code == 403
    with pytest.raises(HTTPException) as backup:
        keys.create_key(session, key_payload(secret, auth_store, recovery=True, code=codes[0]), 'test')
    assert backup.value.status_code == 403
    created = keys.create_key(session, key_payload(secret, auth_store), 'test')
    with keys.connect() as connection:
        connection.execute("UPDATE personal_api_keys SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (created['key']['id'],))
    with pytest.raises(HTTPException) as expired:
        keys.authenticate_key('Bearer ' + created['secret'])
    assert expired.value.status_code == 401


@pytest.mark.parametrize('authorization', [None, 'Bearer wrong', 'Basic emk_x', 'Bearer emk_'+'x'*1000])
def test_invalid_tokens_rejected_without_fallback(auth_store, authorization):
    with pytest.raises(HTTPException) as rejected:
        APIKeyStore(auth_store.config).authenticate_key(authorization)
    assert rejected.value.status_code == 401


def test_personal_routes_reject_service_bearer_and_cross_site_requests(auth_store, app_module, api_app):
    keys, user, session, payload, created = issue(auth_store, app_module)
    client = TestClient(api_app, base_url=ORIGIN, cookies={'emulytix_session': session})
    assert client.get('/api/v1/devices').status_code == 401
    assert client.get('/api/v1/devices', headers={'Authorization': 'Bearer emulytix-integration-test-token'}).status_code == 401
    headers = {'Authorization': 'Bearer '+created['secret']}
    assert client.get('/api/v1/capabilities', headers=headers).json()['scopes'] == created['key']['scopes']
    assert client.get('/api/v1/devices', headers=headers).status_code == 200
    assert client.get('/api/v1/devices', headers={**headers, 'Origin': 'https://evil.test'}).status_code == 403
    assert client.post('/api/v1/runs', headers=headers, json={'bad': 'body'}).status_code == 422
    assert client.get('/console/account/api-keys', headers={'Authorization': 'Bearer '+created['secret']}, cookies={'emulytix_session': ''}).status_code == 401
    no_session = TestClient(api_app, base_url=ORIGIN, headers={'Authorization': 'Bearer emulytix-integration-test-token'})
    assert no_session.get('/console/account/api-keys').status_code == 401
    # An API key never grants permission on private routes outside the versioned API.
    assert TestClient(app_module.app, base_url=ORIGIN, headers=headers).get('/console/users').status_code == 401


def test_external_runs_replay_namespace_scopes_and_cancellation(auth_store, app_module, api_app, workflow_payload, run_payload):
    keys, user, session, payload, created = issue(auth_store, app_module, scopes=['runs.execute', 'runs.cancel', 'runs.read'])
    business = RunStore(keys.config.dsn)
    business.register_device(DeviceRegistration(device_id='phone-1', host_id='host-1', serial='emulator-5554', kind='emulator'))
    business.register_workflow(WorkflowRegistration.model_validate(workflow_payload))
    client = TestClient(api_app, base_url=ORIGIN, headers={'Authorization': 'Bearer '+created['secret']})
    assert client.get('/api/v1/devices').status_code == 403
    first = client.post('/api/v1/runs', json=run_payload)
    assert first.status_code == 202, first.text
    run_id = first.json()['id']
    assert client.post('/api/v1/runs', json=run_payload).json()['id'] == run_id
    with keys.connect() as connection:
        mapping = connection.execute('SELECT * FROM personal_api_run_requests').fetchone()
        assert str(mapping['run_id']) == run_id and str(mapping['user_id']) == user['id']
        assert mapping['client_key_hash'] == hashlib.sha256(run_payload['idempotency_key'].encode()).hexdigest()
    assert client.post('/api/v1/runs', json={**run_payload, 'parameters': {'changed': True}}).status_code == 409
    assert client.get('/api/v1/runs/'+run_id).status_code == 200
    assert client.get('/api/v1/runs/'+run_id+'/events').status_code == 200
    assert client.get('/api/v1/runs?limit=1').json()['items'][0]['id'] == run_id
    assert client.post('/api/v1/runs/'+run_id+'/cancel', json={}).json()['status'] == 'cancelled'
    _, _, _, _, second = issue(auth_store, app_module, scopes=['runs.execute'])
    other = TestClient(api_app, base_url=ORIGIN, headers={'Authorization': 'Bearer '+second['secret']})
    assert other.post('/api/v1/runs', json=run_payload).json()['id'] != run_id
    assert other.post('/api/v1/runs/'+run_id+'/cancel', json={}).status_code == 403


def test_api_rejects_reserved_public_key_and_unproven_legacy_alias(auth_store, app_module, api_app, workflow_payload, run_payload):
    from app.run_models import RunSubmission
    keys, user, session, payload, created = issue(auth_store, app_module, scopes=['runs.execute'])
    business = RunStore(keys.config.dsn)
    business.register_device(DeviceRegistration(device_id='phone-1', host_id='host-1', serial='emulator-5554', kind='emulator'))
    business.register_workflow(WorkflowRegistration.model_validate(workflow_payload))
    internal_key = 'api-'+hashlib.sha256((user['id']+'\0'+run_payload['idempotency_key']).encode()).hexdigest()
    collision = RunSubmission.model_validate({**run_payload, 'idempotency_key': internal_key})
    with pytest.raises(HTTPException) as reserved:
        business.submit_run(collision)
    assert reserved.value.status_code == 422
    with business.connect() as connection:
        old = business._submit_run(connection, collision)
        connection.execute("UPDATE runs SET status='succeeded' WHERE id=%s", (old['id'],))
        connection.execute("UPDATE executions SET status='succeeded' WHERE run_id=%s", (old['id'],))
    client = TestClient(api_app, base_url=ORIGIN, headers={'Authorization': 'Bearer '+created['secret']})
    assert client.post('/api/v1/runs', json=run_payload).status_code == 409
    with business.connect() as connection:
        assert connection.execute('SELECT count(*) AS n FROM personal_api_run_requests').fetchone()['n'] == 0
        assert connection.execute('SELECT attempt FROM executions WHERE run_id=%s', (old['id'],)).fetchone()['attempt'] == 1


def test_api_mutation_rechecks_a_key_revoked_after_middleware(auth_store, app_module, api_app, workflow_payload, run_payload, monkeypatch):
    from app import personal_api_routes
    keys, user, session, payload, created = issue(auth_store, app_module, scopes=['runs.execute'])
    business = RunStore(keys.config.dsn)
    business.register_device(DeviceRegistration(device_id='phone-1', host_id='host-1', serial='emulator-5554', kind='emulator'))
    business.register_workflow(WorkflowRegistration.model_validate(workflow_payload))
    original = personal_api_routes.scoped
    def revoke_between_auth_and_write(value, scope):
        keys.revoke_key(session, created['key']['id'])
        original(value, scope)
    monkeypatch.setattr(personal_api_routes, 'scoped', revoke_between_auth_and_write)
    client = TestClient(api_app, base_url=ORIGIN, headers={'Authorization': 'Bearer '+created['secret']})
    assert client.post('/api/v1/runs', json=run_payload).status_code == 401
    with business.connect() as connection:
        assert connection.execute('SELECT count(*) AS n FROM runs').fetchone()['n'] == 0


def test_management_creation_requires_cookie_csrf_confirmation_and_once_only(auth_store, app_module, api_app):
    user, secret, session, codes, _ = enabled_session(auth_store, app_module, 'viewer')
    client = TestClient(api_app, base_url=ORIGIN, cookies={'emulytix_session': session})
    payload = key_payload(secret, auth_store).model_dump()
    assert client.post('/console/account/api-keys', json=payload).status_code == 403
    headers = {'Origin': ORIGIN, 'X-Emulytix-Client': 'console'}
    created = client.post('/console/account/api-keys', headers=headers, json=payload)
    assert created.status_code == 201, created.text
    assert created.headers['cache-control'] == 'no-store'
    assert client.post('/console/account/api-keys', headers=headers, json=payload).status_code == 409
    key_id = created.json()['key']['id']
    assert created.json()['secret'] not in client.get('/console/account/api-keys').text
    assert client.delete('/console/account/api-keys/'+key_id, headers={**headers, 'Content-Type': 'application/json'}).status_code == 200


def test_api_rate_limit_is_shared_and_revocation_is_immediate(auth_store, app_module):
    keys, user, session, payload, created = issue(auth_store, app_module)
    keys.authenticate_key('Bearer '+created['secret'])
    with keys.connect() as connection:
        connection.execute('UPDATE auth_rate_limits SET attempts=600 WHERE bucket_key=%s', (digest('personal-api:'+created['key']['id']),))
    with pytest.raises(HTTPException) as limited:
        APIKeyStore(keys.config).authenticate_key('Bearer '+created['secret'])
    assert limited.value.status_code == 429 and limited.value.headers['Retry-After'] == '60'


def test_mcp_adapter_calls_the_real_scoped_rest_api_over_loopback(auth_store, app_module, api_app, workflow_payload, run_payload):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from test_mcp_adapter import mcp, request
    keys, user, session, payload, created = issue(auth_store, app_module, scopes=['devices.read', 'workflows.read', 'runs.read', 'runs.execute', 'runs.cancel'])
    business = RunStore(keys.config.dsn)
    business.register_device(DeviceRegistration(device_id='phone-1', host_id='host-1', serial='emulator-5554', kind='emulator'))
    business.register_workflow(WorkflowRegistration.model_validate(workflow_payload))
    backend = TestClient(api_app, base_url=ORIGIN)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def handle_request(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            response = backend.request(self.command, self.path, content=body, headers={
                'Authorization': self.headers.get('Authorization', ''), 'Content-Type': 'application/json',
            })
            self.send_response(response.status_code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(response.content)
        do_GET = handle_request
        do_POST = handle_request
    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        server = mcp.Server(mcp.API('http://127.0.0.1:'+str(http.server_port), created['secret']))
        server.handle(request('initialize', {'protocolVersion': mcp.PROTOCOL, 'capabilities': {}, 'clientInfo': {'name': 'integration', 'version': '1'}}))
        server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        tools = server.handle(request('tools/list'))['result']['tools']
        assert 'start_run' in [tool['name'] for tool in tools]
        devices = server.handle(request('tools/call', {'name': 'list_devices'}))['result']
        assert not devices['isError'] and devices['structuredContent']['items'][0]['device_id'] == 'phone-1'
        launched = server.handle(request('tools/call', {'name': 'start_run', 'arguments': run_payload}))['result']
        assert not launched['isError'], launched
        run_id = launched['structuredContent']['id']
        replay = server.handle(request('tools/call', {'name': 'start_run', 'arguments': run_payload}))['result']
        assert replay['structuredContent']['id'] == run_id
        cancelled = server.handle(request('tools/call', {'name': 'cancel_run', 'arguments': {'run_id': run_id}}))['result']
        assert not cancelled['isError'] and cancelled['structuredContent']['status'] == 'cancelled'
        keys.revoke_key(session, created['key']['id'])
        assert 'error' in server.handle(request('tools/list'))
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=3)
