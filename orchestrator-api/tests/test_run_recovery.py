"""Retries preserve successful devices and reject uncertain effects on a disposable database."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb
import pytest

from app.run_models import DeviceRegistration, RunSubmission, WorkflowRegistration
from app.run_recovery import RecoveryStore, RetryInput
from test_authentication import auth_store
from test_user_roles import signed_in


@pytest.fixture
def recovery(database_dsn, workflow_payload):
    store = RecoveryStore(database_dsn)
    for index in range(3):
        store.register_device(DeviceRegistration(device_id='phone-'+str(index), host_id='host', serial='Serial-'+str(index), kind='physical'))
    store.register_workflow(WorkflowRegistration.model_validate(workflow_payload))
    return store


def source_run(store, states=('failed', 'succeeded', 'failed'), *, key=None, workflow='go-home', run_state='failed'):
    run = store.submit_run(RunSubmission(workflow_id=workflow, workflow_version=1, device_ids=['phone-'+str(index) for index in range(len(states))],
        max_concurrency=len(states), parameters={'topic': 'football'}, idempotency_key=key or 'source-'+uuid4().hex))
    with store.connect() as connection:
        connection.execute('UPDATE runs SET status=%s WHERE id=%s', (run_state, run['id']))
        for index, state in enumerate(states):
            connection.execute('UPDATE executions SET status=%s WHERE run_id=%s AND device_id=%s', (state, run['id'], 'phone-'+str(index)))
    return store.get_run(run['id'])


def retry_input(devices=('phone-0',), request_id=None):
    return RetryInput(request_id=request_id or uuid4(), device_ids=list(devices))


def test_retry_only_selected_failures_preserves_version_parameters_and_attempt_history(recovery):
    source = source_run(recovery)
    before = recovery.diagnosis(source['id'])
    assert [item['can_retry'] for item in before['items']] == [True, False, True]
    payload = retry_input(('phone-2', 'phone-0'))
    retried = recovery.retry(source['id'], payload)
    assert retried['device_ids'] == ['phone-2', 'phone-0'] and retried['max_concurrency'] == 2
    assert retried['parameters'] == source['parameters'] and retried['workflow_version'] == source['workflow_version']
    assert all(row['status'] == 'queued' and row['attempt'] == 2 for row in retried['executions'])
    assert 'phone-1' not in {row['device_id'] for row in retried['executions']}
    assert recovery.get_run(source['id'])['executions'] == source['executions']
    assert recovery.diagnosis(retried['id'])['source_run_id'] == source['id']
    assert recovery.diagnosis(source['id'])['active_retry_id'] == retried['id']
    assert recovery.retry(source['id'], payload)['id'] == retried['id']
    with recovery.connect() as connection:
        assert connection.execute('SELECT count(*) AS n FROM runs').fetchone()['n'] == 2
        assert connection.execute('SELECT count(*) AS n FROM run_retries').fetchone()['n'] == 1
    assert any(row['type'] == 'run.retry_created' for row in recovery.list_events(source['id'], 0, 100))


@pytest.mark.parametrize('selected', [('phone-1',), ('missing',), ('phone-0', 'phone-0')])
def test_success_missing_or_duplicate_selection_never_creates_retry(recovery, selected):
    source = source_run(recovery)
    with pytest.raises(HTTPException) as blocked:
        recovery.retry(source['id'], retry_input(selected))
    assert blocked.value.status_code == (422 if len(set(selected)) != len(selected) else 409)
    with recovery.connect() as connection:
        assert connection.execute('SELECT count(*) AS n FROM runs').fetchone()['n'] == 1


@pytest.mark.parametrize('journal_status,non_idempotent', [('intent', False), ('uncertain', False), ('done', True)])
def test_uncertain_or_non_idempotent_journal_prevents_retry(recovery, journal_status, non_idempotent):
    source = source_run(recovery, ('failed',))
    execution = source['executions'][0]
    with recovery.connect() as connection:
        connection.execute('INSERT INTO action_journal(id,execution_id,step_id,lease_epoch,action,non_idempotent,status) VALUES(%s,%s,%s,1,%s,%s,%s)',
            (uuid4(), execution['id'], 'home', Jsonb({'action': 'press_key'}), non_idempotent, journal_status))
    diagnosis = recovery.diagnosis(source['id'])['items'][0]
    assert diagnosis['can_retry'] is False and diagnosis['retry_block'] == 'uncertain_effect'
    with pytest.raises(HTTPException) as blocked:
        recovery.retry(source['id'], retry_input())
    assert blocked.value.status_code == 409


def test_non_idempotent_workflow_is_blocked_even_before_the_effect(recovery, workflow_payload):
    workflow = {**workflow_payload, 'workflow_id': 'non-idempotent', 'steps': [{**workflow_payload['steps'][0], 'non_idempotent': True,
        'verify_after_crash': {'type': 'package', 'value': 'com.android.launcher3'}}]}
    recovery.register_workflow(WorkflowRegistration.model_validate(workflow))
    source = source_run(recovery, ('failed',), workflow='non-idempotent')
    assert recovery.diagnosis(source['id'])['items'][0]['retry_block'] == 'non_idempotent_workflow'
    with pytest.raises(HTTPException) as blocked:
        recovery.retry(source['id'], retry_input())
    assert blocked.value.status_code == 409


@pytest.mark.parametrize('reservation', ['quarantine', 'owned', 'other-queued', 'needs_review', 'source-active'])
def test_reserved_or_uncertain_devices_are_never_retried(recovery, reservation):
    source = source_run(recovery, ('failed',))
    with recovery.connect() as connection:
        if reservation == 'quarantine':
            connection.execute('INSERT INTO device_leases(device_id,quarantined) VALUES(%s,true)', ('phone-0',))
        elif reservation == 'owned':
            connection.execute("INSERT INTO device_leases(device_id,execution_id,owner_id,expires_at) VALUES(%s,%s,'owner',clock_timestamp()+interval '1 minute')", ('phone-0', source['executions'][0]['id']))
        elif reservation == 'needs_review':
            connection.execute("UPDATE executions SET status='needs_review' WHERE id=%s", (source['executions'][0]['id'],))
        elif reservation == 'source-active':
            connection.execute("UPDATE executions SET status='running' WHERE id=%s", (source['executions'][0]['id'],))
    if reservation == 'other-queued':
        recovery.submit_run(RunSubmission(workflow_id='go-home', workflow_version=1, device_ids=['phone-0'], max_concurrency=1, idempotency_key='other-queued'))
    assert recovery.diagnosis(source['id'])['items'][0]['can_retry'] is False
    with pytest.raises(HTTPException) as blocked:
        recovery.retry(source['id'], retry_input())
    assert blocked.value.status_code == 409


def test_diagnosis_reports_the_observed_failure_and_last_capture(recovery):
    source = source_run(recovery, ('failed',))
    execution = source['executions'][0]
    with recovery.connect() as connection:
        connection.execute('UPDATE executions SET error=%s,evidence=%s WHERE id=%s', (
            'Selector not found', Jsonb({'failed_step': 'search', 'steps': [{'step_id': 'open', 'screenshot': 'capture.png'}, {'step_id': 'search'}]}), execution['id']))
    result = recovery.diagnosis(source['id'])['items'][0]
    assert result['code'] == 'element_not_found' and result['failed_step'] == 'search' and result['last_capture_step'] == 'open'


def test_same_request_is_atomic_under_concurrent_delivery(recovery):
    source = source_run(recovery)
    payload = retry_input()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: recovery.retry(source['id'], payload), range(4)))
    assert len({row['id'] for row in results}) == 1
    with pytest.raises(HTTPException) as changed:
        recovery.retry(source['id'], retry_input(('phone-2',), payload.request_id))
    assert changed.value.status_code == 409
    with pytest.raises(HTTPException) as second_active:
        recovery.retry(source['id'], retry_input(('phone-2',)))
    assert second_active.value.status_code == 409
    with recovery.connect() as connection:
        assert connection.execute('SELECT count(*) AS n FROM run_retries').fetchone()['n'] == 1


def test_request_id_reused_for_another_source_returns_conflict(recovery):
    source_one = source_run(recovery, ('failed',))
    source_two = source_run(recovery, ('failed',))
    payload = retry_input()
    child = recovery.retry(source_one['id'], payload)
    with recovery.connect() as connection:
        connection.execute("UPDATE runs SET status='failed' WHERE id=%s", (child['id'],))
        connection.execute("UPDATE executions SET status='failed' WHERE run_id=%s", (child['id'],))
    with pytest.raises(HTTPException) as changed:
        recovery.retry(source_two['id'], payload)
    assert changed.value.status_code == 409


def test_retry_cannot_alias_an_unrelated_ordinary_run_key(recovery):
    source = source_run(recovery, ('failed',))
    payload = retry_input()
    collision = RunSubmission(workflow_id='go-home', workflow_version=1, device_ids=['phone-0'],
        max_concurrency=1, parameters=source['parameters'], idempotency_key='retry:'+str(payload.request_id))
    with pytest.raises(HTTPException) as reserved:
        recovery.submit_run(collision)
    assert reserved.value.status_code == 422
    # Emulate an old row accepted before the public API reserved this namespace.
    with recovery.connect() as connection:
        unrelated = recovery._submit_run(connection, collision)
    with recovery.connect() as connection:
        connection.execute("UPDATE runs SET status='succeeded' WHERE id=%s", (unrelated['id'],))
        connection.execute("UPDATE executions SET status='succeeded' WHERE run_id=%s", (unrelated['id'],))
    try:
        result = recovery.retry(source['id'], payload)
    except HTTPException as rejected:
        assert rejected.status_code == 409
    else:
        assert result['id'] != unrelated['id'], 'A retry must not reuse or rewrite another run from the ordinary submission API'


def test_retry_rechecks_actor_permissions_in_its_transaction(auth_store, app_module, recovery):
    user, client, _ = signed_in(auth_store, app_module, 'builder')
    source = source_run(recovery, ('failed',))
    with auth_store.connect() as connection:
        connection.execute("UPDATE auth_users SET role='viewer' WHERE id=%s", (user['id'],))
    with pytest.raises(HTTPException) as forbidden:
        from uuid import UUID
        recovery.retry(source['id'], retry_input(), UUID(user['id']))
    assert forbidden.value.status_code == 403


@pytest.mark.parametrize('role', ['admin', 'builder', 'operator', 'viewer', 'auditor'])
def test_retry_and_diagnosis_permissions(auth_store, app_module, recovery, role):
    user, client, _ = signed_in(auth_store, app_module, role)
    source = source_run(recovery, ('failed',))
    assert client.get(f'/runs/{source["id"]}/diagnosis').status_code == 200
    response = client.post(f'/runs/{source["id"]}/retry', json=retry_input().model_dump(mode='json'))
    assert response.status_code == (202 if role in {'admin', 'builder', 'operator'} else 403), response.text
