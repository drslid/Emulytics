from uuid import UUID, uuid4

import psycopg
import pytest

from app.emulator_store import EmulatorStore
from app.execution_store import ExecutionStore
from app.telemetry import heartbeat
from test_authentication import auth_store
from test_user_roles import signed_in


def test_device_edits_require_permission_and_keep_identity(auth_store, app_module):
    _, operator, _ = signed_in(auth_store, app_module, 'operator')
    _, viewer, _ = signed_in(auth_store, app_module, 'viewer')
    registration = {'device_id': 'first-phone', 'host_id': 'host-1', 'serial': 'serial-1', 'kind': 'physical'}
    assert operator.post('/devices', json=registration).status_code == 201
    route = '/console/devices/first-phone'
    assert viewer.patch(route, json={'display_name': 'Studio'}).status_code == 403
    json_headers = {'Content-Type': 'application/json'}
    assert viewer.delete(route, headers=json_headers).status_code == 403
    for payload in ({'display_name': ' '}, {'display_name': 'Studio', 'serial': 'other'}):
        assert operator.patch(route, json=payload).status_code == 422
    renamed = operator.patch(route, json={'display_name': '  Studio de Paris  '})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json() == {**registration, 'display_name': 'Studio de Paris',
                              'status': 'registered', 'created_at': renamed.json()['created_at']}
    assert operator.delete(route, headers=json_headers).status_code == 204
    assert operator.get('/devices').json()['items'] == []
    assert operator.get('/console/fleet').json()['items'] == []


def test_removal_blocks_active_work_and_preserves_finished_execution_and_group_revision(
    control_client, registered, database_dsn, run_payload,
):
    route = '/console/devices/phone-1'
    group = control_client.post('/console/fleet/groups', json={'name': 'Studio', 'device_ids': ['phone-1']}).json()
    run = control_client.post('/runs', json=run_payload).json()
    execution_id = UUID(run['executions'][0]['id'])
    busy = control_client.delete(route)
    assert busy.status_code == 409 and busy.json()['detail']['code'] == 'device_busy'
    leases = ExecutionStore(database_dsn)
    grant = leases.claim(execution_id, 'worker-one', 30, host_id='host-1')
    assert control_client.delete(route).json()['detail']['code'] == 'device_busy'
    assert leases.finish(execution_id, 'worker-one', grant['lease_epoch'], 'failed', error='Demo')
    assert control_client.delete(route).status_code == 204
    assert control_client.delete(route).status_code == 204
    assert control_client.patch(route, json={'display_name': 'Deleted'}).status_code == 404
    assert control_client.get(f'{route}/screen').status_code == 404
    assert control_client.get('/console/summary').json()['devices_total'] == 0
    assert control_client.get(f"/runs/{run['run_id']}").json()['executions'][0]['id'] == str(execution_id)
    assert control_client.get(f"/runs/{run['run_id']}/diagnosis").json()['items'][0]['retry_block'] == 'device_removed'
    assert control_client.post('/runs', json={**run_payload, 'idempotency_key': 'new-run'}).status_code == 404
    changed = control_client.get(f"/console/fleet/groups/{group['id']}").json()['group']
    assert changed['device_ids'] == [] and changed['revision'] == group['revision'] + 1

    registration = {'host_id': 'host-1', 'serial': 'emulator-5554', 'kind': 'emulator'}
    assert control_client.post('/devices', json={**registration, 'device_id': 'phone-1'}).status_code == 409
    assert control_client.post('/devices', json={**registration, 'device_id': 'phone-2'}).status_code == 201
    with pytest.raises(psycopg.errors.ForeignKeyViolation), leases.connect() as connection:
        connection.execute('INSERT INTO executions(id,run_id,device_id,attempt) VALUES(%s,%s,%s,2)',
                           (uuid4(), run['run_id'], 'phone-1'))


def test_managed_removal_requires_stop_and_releases_slot_without_reusing_identity(control_client, database_dsn):
    heartbeat(database_dsn, 'worker', 'worker-one', 'host-1', metrics={'managed_emulators': True})
    config = {'name': 'Studio Android', 'host_id': 'host-1', 'application_ids': ['chrome'], 'idempotency_key': 'create-one'}
    original = control_client.post('/console/emulators', json=config).json()
    device_id = original['device_id']
    store = EmulatorStore(database_dsn)
    with store.connect() as connection:
        connection.execute("UPDATE managed_emulators SET state='running' WHERE device_id=%s", (device_id,))
    route = f'/console/devices/{device_id}'
    assert control_client.delete(route).json()['detail']['code'] == 'stop_emulator_first'
    stopped = control_client.post(f'/console/emulators/{device_id}/stop', json={'idempotency_key': 'stop-one'})
    assert stopped.status_code == 202, stopped.text
    operation = stopped.json()
    assert control_client.delete(route).json()['detail']['code'] == 'device_busy'
    execution = control_client.get(f"/runs/{operation['run_id']}").json()['executions'][0]
    execution_id = UUID(execution['id'])
    leases = ExecutionStore(database_dsn)
    grant = leases.claim(execution_id, 'worker-one', 30, host_id='host-1')
    assert store.update_runtime(device_id, 'stopped', execution_id=execution_id, owner_id='worker-one', lease_epoch=grant['lease_epoch'])
    assert leases.finish(execution_id, 'worker-one', grant['lease_epoch'], 'succeeded')
    assert control_client.delete(route).status_code == 204
    assert control_client.get('/console/emulators').json()['items'] == []
    assert store.list_managed('host-1') == []
    assert control_client.post(f'/console/emulators/{device_id}/start', json={'idempotency_key': 'power-on'}).status_code == 404
    assert control_client.post('/console/emulators', json=config).status_code == 409
    replacement = control_client.post('/console/emulators', json={**config, 'idempotency_key': 'create-new'}).json()
    assert replacement['slot'] == original['slot'] and replacement['serial'] == original['serial']
    assert replacement['id'] != original['id'] and replacement['device_id'] != device_id
    with store.connect() as connection:
        retired = connection.execute('SELECT id,deleted_at FROM managed_emulator_records WHERE device_id=%s', (device_id,)).fetchone()
        assert str(retired['id']) == original['id'] and retired['deleted_at'] is not None


def test_enabled_schedule_prevents_removal_and_retired_devices_cannot_resume(
    auth_store, app_module, workflow_payload,
):
    _, operator, _ = signed_in(auth_store, app_module, 'operator')
    _, builder, _ = signed_in(auth_store, app_module, 'builder')
    assert operator.post('/devices', json={'device_id': 'phone-1', 'host_id': 'host-1',
                                          'serial': 'serial-1', 'kind': 'physical'}).status_code == 201
    assert builder.post('/workflows', json=workflow_payload).status_code == 201
    payload = {'name': 'Morning', 'workflow_id': 'go-home', 'workflow_version': 1, 'device_ids': ['phone-1'],
               'max_concurrency': 1, 'cron': '0 9 * * *', 'timezone': 'UTC', 'enabled': True}
    created = operator.post('/console/schedules', json=payload)
    assert created.status_code == 201, created.text
    schedule = f"/console/schedules/{created.json()['id']}"
    device = '/console/devices/phone-1'
    blocked = operator.request('DELETE', device, json={})
    assert blocked.status_code == 409 and blocked.json()['detail']['code'] == 'device_scheduled'
    assert operator.patch(schedule, json={'enabled': False}).status_code == 200
    assert operator.request('DELETE', device, json={}).status_code == 204
    assert operator.patch(schedule, json={'enabled': True}).status_code == 409
    assert operator.post('/console/schedules', json=payload).status_code == 404
