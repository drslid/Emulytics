"""Fleet actions use disposable PostgreSQL; no Docker or Android effect is performed."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from uuid import UUID, uuid4

from fastapi import HTTPException
import pytest

from app.emulator_store import EmulatorStore
from app.execution_store import ExecutionStore
from app.fleet_routes import BulkInput, FleetStore, GroupInput, GroupUpdate
from app.run_models import DeviceRegistration, RunSubmission, WorkflowRegistration
from app.telemetry import heartbeat
from test_authentication import auth_store
from test_user_roles import signed_in


@pytest.fixture
def fleet(database_dsn):
    store = FleetStore(database_dsn)
    for name in ['one', 'two', 'three']:
        store.register_device(DeviceRegistration(device_id='phone-'+name, host_id='host-one', serial='Serial-'+name, kind='physical'))
    return store


def test_groups_normalize_names_update_members_with_revision_and_delete(fleet):
    first = fleet.save_group(GroupInput(name='  Équipe    Paris  ', device_ids=['phone-two', 'phone-one']))
    assert first['name'] == 'Équipe Paris' and first['revision'] == 1
    assert first['device_ids'] == ['phone-one', 'phone-two']
    assert fleet.groups()['items'][0]['id'] == first['id']
    detail = fleet.group_detail(first['id'])
    assert len(detail['devices']) == 2 and all(row['connection_status'] == 'worker_offline' for row in detail['devices'])
    updated = fleet.save_group(GroupUpdate(name='Équipe Lyon', device_ids=['phone-three'], revision=1), group_id=first['id'])
    assert updated['revision'] == 2 and updated['device_ids'] == ['phone-three']
    with pytest.raises(HTTPException) as stale:
        fleet.save_group(GroupUpdate(name='Stale', device_ids=['phone-one'], revision=1), group_id=first['id'])
    assert stale.value.status_code == 409 and fleet.group_detail(first['id'])['group']['name'] == 'Équipe Lyon'
    with pytest.raises(HTTPException) as duplicate:
        fleet.save_group(GroupInput(name='équipe lyon', device_ids=['phone-one']))
    assert duplicate.value.status_code == 409
    with pytest.raises(HTTPException) as missing:
        fleet.save_group(GroupInput(name='Missing', device_ids=['missing-device']))
    assert missing.value.status_code == 404 and len(fleet.groups()['items']) == 1
    fleet.delete_group(first['id'])
    assert fleet.groups()['items'] == []
    with fleet.connect() as connection:
        assert connection.execute('SELECT count(*) AS n FROM device_group_members').fetchone()['n'] == 0
        assert connection.execute('SELECT count(*) AS n FROM devices').fetchone()['n'] == 3


@pytest.mark.parametrize('role', ['admin', 'operator', 'builder', 'viewer', 'auditor'])
def test_fleet_permissions_enforced_for_every_role(auth_store, app_module, fleet, role):
    user, client, _ = signed_in(auth_store, app_module, role)
    assert client.get('/console/fleet/groups').status_code == 200
    assert client.get('/console/fleet/capacity').status_code == 200
    allowed = role in {'admin', 'operator'}
    created = client.post('/console/fleet/groups', json={'name': 'Group', 'device_ids': ['phone-one']})
    assert created.status_code == (201 if allowed else 403), created.text
    assert client.post('/console/fleet/bulk', json={}).status_code == (422 if allowed else 403)
    if allowed:
        identity = created.json()['id']
        assert client.patch('/console/fleet/groups/'+identity, json={'name': 'Renamed', 'device_ids': ['phone-two'], 'revision': 1}).status_code == 200
        assert client.delete('/console/fleet/groups/'+identity, headers={'Content-Type': 'application/json'}).status_code == 204
    else:
        assert client.patch('/console/fleet/groups/'+str(uuid4()), json={}).status_code == 403
        assert client.delete('/console/fleet/groups/'+str(uuid4()), headers={'Content-Type': 'application/json'}).status_code == 403


def test_capacity_counts_live_workers_not_devices_and_excludes_stopped_emulators(fleet, workflow_payload):
    observed = [{'serial': 'Serial-'+name, 'state': 'device'} for name in ['one', 'two', 'three']]
    heartbeat(fleet.dsn, 'worker', 'one', 'host-one', metrics={'adb_status': 'ready', 'devices': observed, 'managed_emulators': True})
    heartbeat(fleet.dsn, 'worker', 'stale', 'host-one', metrics={'adb_status': 'ready', 'devices': observed})
    heartbeat(fleet.dsn, 'worker', 'starting', 'host-one', status='starting', metrics={'adb_status': 'ready', 'devices': observed})
    heartbeat(fleet.dsn, 'api', 'not-a-worker', 'host-one')
    with fleet.connect() as connection:
        connection.execute("UPDATE service_heartbeats SET last_seen_at=clock_timestamp()-interval '21 seconds' WHERE instance_id='stale'")
    emulator = EmulatorStore(fleet.dsn).create_emulator('Stopped', 'host-one', ['chrome'], 'capacity-emulator')[0]
    heartbeat(fleet.dsn, 'worker', 'one', 'host-one', metrics={'adb_status': 'ready', 'devices': observed+[{'serial': emulator['serial'], 'state': 'device'}], 'managed_emulators': True})
    result = fleet.capacity()
    assert result['worker_slots'] == 1 and result['connected_devices'] == 4
    assert result['ready_devices'] == 3 and result['available_slots'] == 1 and result['active_slots'] == 0
    fleet.register_workflow(WorkflowRegistration.model_validate(workflow_payload))
    run = fleet.submit_run(RunSubmission(workflow_id='go-home', workflow_version=1, device_ids=['phone-one'], max_concurrency=1, idempotency_key='occupy'))
    assert ExecutionStore(fleet.dsn).claim(run['executions'][0]['id'], 'worker-one', 60, host_id='host-one')
    busy = fleet.capacity()
    assert busy['active_slots'] == 1 and busy['available_slots'] == 0 and busy['ready_devices'] == 2
    heartbeat(fleet.dsn, 'worker', 'second', 'host-one', metrics={'adb_status': 'ready', 'devices': observed})
    assert fleet.capacity()['available_slots'] == 1


def managed_pair(fleet):
    heartbeat(fleet.dsn, 'worker', 'manager', 'host-one', metrics={'managed_emulators': True})
    store = EmulatorStore(fleet.dsn)
    return [store.create_emulator('Managed '+str(index), 'host-one', ['chrome'], 'create-'+str(index))[0] for index in range(2)]


def test_bulk_mixed_selection_preserves_rejections_and_replays_without_duplicate_jobs(fleet):
    first, second = managed_pair(fleet)
    payload = BulkInput(request_id=uuid4(), action='start', device_ids=[first['device_id'], 'phone-one', 'missing'])
    result = fleet.bulk(payload)
    assert [item['status'] for item in result['items']] == ['accepted', 'rejected', 'rejected']
    run_id = result['items'][0]['run_id']
    assert fleet.bulk(payload) == result
    ExecutionStore(fleet.dsn).cancel_run(UUID(run_id))
    assert fleet.bulk(payload) == result
    with fleet.connect() as connection:
        assert connection.execute('SELECT count(*) AS n FROM runs').fetchone()['n'] == 1
    with pytest.raises(HTTPException) as changed:
        fleet.bulk(BulkInput(request_id=payload.request_id, action='stop', device_ids=payload.device_ids))
    assert changed.value.status_code == 409


def test_bulk_recovers_partial_unknown_failure_using_same_per_device_keys(fleet, monkeypatch):
    first, second = managed_pair(fleet)
    payload = BulkInput(request_id=uuid4(), action='start', device_ids=[first['device_id'], second['device_id']])
    original = EmulatorStore.queue_operation
    calls = []
    fail_once = [True]
    def queue(self, device_id, *args, **kwargs):
        calls.append(device_id)
        if device_id == second['device_id'] and fail_once:
            fail_once.pop()
            raise HTTPException(503, 'Unknown database response')
        return original(self, device_id, *args, **kwargs)
    monkeypatch.setattr(EmulatorStore, 'queue_operation', queue)
    with pytest.raises(HTTPException) as unknown:
        fleet.bulk(payload)
    assert unknown.value.status_code == 503
    result = fleet.bulk(payload)
    assert all(item['status'] == 'accepted' for item in result['items'])
    assert calls.count(first['device_id']) == 1 and calls.count(second['device_id']) == 2
    assert fleet.bulk(payload) == result
    with fleet.connect() as connection:
        assert connection.execute('SELECT count(*) AS n FROM runs').fetchone()['n'] == 2


def test_concurrent_group_names_return_conflict_without_database_exception(fleet, monkeypatch):
    one = fleet.save_group(GroupInput(name='One', device_ids=['phone-one']))
    two = fleet.save_group(GroupInput(name='Two', device_ids=['phone-two']))
    gate = Barrier(2)
    original = FleetStore.connect
    class Guarded:
        def __init__(self, connection): self.connection = connection
        def __getattr__(self, name): return getattr(self.connection, name)
        def execute(self, query, *args, **kwargs):
            result = self.connection.execute(query, *args, **kwargs)
            if query.startswith('SELECT id FROM device_groups WHERE lower(name)'):
                gate.wait(timeout=10)
            return result
    @contextmanager
    def connect(self):
        with original(self) as connection: yield Guarded(connection)
    monkeypatch.setattr(FleetStore, 'connect', connect)
    def rename(group):
        try:
            fleet.save_group(GroupUpdate(name='Shared', device_ids=group['device_ids'], revision=1), group_id=group['id'])
            return 200
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(rename, [one, two])) == [200, 409]
