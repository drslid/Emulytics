"""Hardware changes preserve userdata and are admitted only while stopped."""
from uuid import UUID

from fastapi import HTTPException
import pytest

from app.emulator_hardware import DEFAULT_HARDWARE, EmulatorHardware
from app.emulator_store import EmulatorStore
from app.execution_store import ExecutionStore
from app.telemetry import heartbeat


@pytest.fixture
def store(database_dsn):
    heartbeat(database_dsn, 'worker', 'hardware-worker', 'host-one', metrics={'managed_emulators': True})
    return EmulatorStore(database_dsn)


def create(store, **changes):
    return store.create_emulator('Phone', 'host-one', ['chrome'], 'hardware-create', **changes)[0]


@pytest.mark.parametrize('change', [
    {'ram_mb': True}, {'ram_mb': '2048'}, {'ram_mb': 9000}, {'ram_mb': 1100},
    {'cpu_cores': 0}, {'cpu_cores': 9}, {'width': 721}, {'height': 4000},
    {'density': 50}, {'storage_gb': 1}, {'storage_gb': 65}, {'shell': 'reboot'},
])
def test_untrusted_hardware_is_rejected(change):
    with pytest.raises(ValueError):
        EmulatorHardware.model_validate({**DEFAULT_HARDWARE, **change})


def test_creation_defaults_and_hardware_are_idempotent(store):
    emulator = create(store)
    assert emulator['hardware'] == DEFAULT_HARDWARE
    assert emulator['applied_hardware'] is None
    assert emulator['storage_editable'] is True
    assert create(store)['id'] == emulator['id']
    with pytest.raises(HTTPException) as error:
        create(store, hardware={**DEFAULT_HARDWARE, 'ram_mb': 2048})
    assert error.value.status_code == 409


def test_stopped_changes_preserve_apps_and_queue_pins_hardware(store):
    emulator = create(store, hardware={**DEFAULT_HARDWARE, 'storage_gb': 16})
    configured = store.configure(emulator['device_id'], ['chrome'], hardware={**emulator['hardware'], 'ram_mb': 2048})
    assert configured['hardware']['ram_mb'] == 2048
    queued = store.queue_operation(emulator['device_id'], 'start', 'hardware-start')
    run = store.get_run(queued['run_id'])
    operation = store.operation(run['executions'][0]['id'])
    assert operation['hardware'] == configured['hardware']
    with pytest.raises(HTTPException) as error:
        store.configure(emulator['device_id'], ['chrome'], hardware={**configured['hardware'], 'cpu_cores': 4})
    assert error.value.status_code == 409


def test_running_changes_are_rejected_but_app_only_configuration_remains_compatible(store):
    emulator = create(store)
    with store.connect() as connection:
        connection.execute("UPDATE managed_emulators SET state='running' WHERE device_id=%s", (emulator['device_id'],))
    assert store.configure(emulator['device_id'], ['chrome', 'instagram'])['state'] == 'running'
    with pytest.raises(HTTPException) as error:
        store.configure(emulator['device_id'], ['chrome'], hardware={**DEFAULT_HARDWARE, 'width': 1080, 'height': 1920})
    assert error.value.status_code == 409


@pytest.mark.parametrize('storage_gb', [2, 16])
def test_existing_userdata_storage_is_never_resized_or_destroyed(store, storage_gb):
    emulator = create(store)
    run = store.get_run(store.queue_operation(emulator['device_id'], 'start', 'initialise')['run_id'])
    ExecutionStore(store.dsn).cancel_run(run['id'])
    with store.connect() as connection:
        connection.execute("UPDATE managed_emulators SET state='stopped' WHERE device_id=%s", (emulator['device_id'],))
    with pytest.raises(HTTPException) as error:
        store.configure(emulator['device_id'], ['chrome'], hardware={**DEFAULT_HARDWARE, 'storage_gb': storage_gb})
    assert error.value.status_code == 409
    assert store.managed_device(emulator['device_id'])['hardware'] == DEFAULT_HARDWARE
    assert store.configure(emulator['device_id'], ['chrome'], hardware={**DEFAULT_HARDWARE, 'cpu_cores': 4})['hardware']['cpu_cores'] == 4


def test_applied_hardware_requires_current_lease(store):
    emulator = create(store)
    run = store.get_run(store.queue_operation(emulator['device_id'], 'start', 'initialise')['run_id'])
    execution_id = run['executions'][0]['id']
    runtime = ExecutionStore(store.dsn)
    grant = runtime.claim(execution_id, 'hardware-worker', 30)
    assert not store.update_runtime(emulator['device_id'], 'running', applied_hardware=DEFAULT_HARDWARE,
        execution_id=execution_id, owner_id='other', lease_epoch=grant['lease_epoch'])
    assert store.update_runtime(emulator['device_id'], 'running', applied_hardware=DEFAULT_HARDWARE,
        execution_id=execution_id, owner_id='hardware-worker', lease_epoch=grant['lease_epoch'])
    applied = store.managed_device(emulator['device_id'])['applied_hardware']
    assert 'storage_gb' not in applied and applied['storage_capacity_bytes'] is None
    assert applied['ram_mb'] == DEFAULT_HARDWARE['ram_mb']


def test_old_applied_disk_defaults_are_never_reported_as_an_effective_capacity(store):
    from psycopg.types.json import Jsonb
    emulator = create(store)
    with store.connect() as connection:
        connection.execute('UPDATE managed_emulators SET applied_hardware=%s WHERE device_id=%s',(Jsonb(DEFAULT_HARDWARE),emulator['device_id']))
    applied = store.managed_device(emulator['device_id'])['applied_hardware']
    assert 'storage_gb' not in applied and applied['storage_capacity_bytes'] is None


def test_route_validation_and_backward_compatible_configuration(control_client, store):
    payload = {'name': 'Hardware phone', 'host_id': 'host-one', 'application_ids': ['chrome'], 'idempotency_key': 'api-create'}
    assert control_client.post('/console/emulators', json={**payload, 'hardware': {'cpu_cores': True}}).status_code == 422
    created = control_client.post('/console/emulators', json={**payload, 'hardware': {**DEFAULT_HARDWARE, 'ram_mb': 2048}})
    assert created.status_code == 201, created.text
    emulator = created.json()
    assert emulator['hardware']['ram_mb'] == 2048
    saved = control_client.post(f"/console/emulators/{emulator['device_id']}/configuration", json={'application_ids': ['chrome', 'instagram']})
    assert saved.status_code == 200 and saved.json()['hardware'] == emulator['hardware']
