from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.emulator_store import EmulatorStore
from app.execution_store import ExecutionStore
from app.journey_context import journey_context
from app.run_models import DeviceRegistration
from app.run_store import RunStore
from app.telemetry import heartbeat


def test_journey_context_without_device_uses_fixed_app_reference_without_reading_inventory():
    store = Mock(spec=RunStore)
    context = journey_context(store, None)
    assert list(context) == ['reference_apps']
    assert context['reference_apps']['Google Chrome'] == 'com.android.chrome'
    store.connect.assert_not_called()


@pytest.mark.parametrize('kind', ['physical', 'emulator'])
def test_external_device_context_omits_identity_and_unknown_apps(database_dsn, kind):
    store = RunStore(database_dsn)
    store.register_device(DeviceRegistration(device_id='device', host_id='private-host', serial='private-serial',
                                             display_name='private name', kind=kind))
    assert journey_context(store, 'device') == {
        **journey_context(store, None), 'device_kind': kind, 'installed_packages': None,
    }
    with store.connect() as connection:
        connection.execute("UPDATE device_records SET deleted_at=clock_timestamp() WHERE device_id='device'")
    with pytest.raises(HTTPException) as error:
        journey_context(store, 'device')
    assert error.value.status_code == 404 and error.value.detail == 'Device not found'


def test_journey_context_uses_only_bounded_successful_managed_package_observations(database_dsn):
    store = EmulatorStore(database_dsn)
    heartbeat(database_dsn, 'worker', 'worker-a', 'host-a', metrics={'managed_emulators': True})
    emulator, _ = store.create_emulator('Private label', 'host-a', ['chrome'], 'create')
    device_id = emulator['device_id']
    reference = journey_context(store, None)
    unknown = {**reference, 'device_kind': 'emulator', 'installed_packages': None}
    assert journey_context(store, device_id) == unknown
    operation = store.queue_operation(device_id, 'prepare', 'prepare')
    execution = store.get_run(operation['run_id'])['executions'][0]['id']
    executions = ExecutionStore(database_dsn)
    grant = executions.claim(execution, 'worker-a', 30)
    packages = ['com.android.chrome', 'com.android.chrome', 'private text', {'token': 'private-token'},
                'com.' + 'x' * 201, *[f'com.example.app{i:02d}' for i in range(25)]]
    assert store.update_runtime(device_id, 'ready', installed_packages=packages, execution_id=execution,
                                owner_id='worker-a', lease_epoch=grant['lease_epoch'])
    assert journey_context(store, device_id) == unknown
    assert executions.finish(execution, 'worker-a', grant['lease_epoch'], 'succeeded')
    assert journey_context(store, device_id) == {
        **reference,
        'device_kind': 'emulator',
        'installed_packages': ['com.android.chrome', *[f'com.example.app{i:02d}' for i in range(23)]],
    }
    store.queue_operation(device_id, 'stop', 'stop')
    assert journey_context(store, device_id) == unknown
