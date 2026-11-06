import pytest

from app.emulator_store import EmulatorStore
from app.telemetry import heartbeat
from test_authentication import auth_store
from test_user_roles import signed_in


@pytest.mark.parametrize('role', ['admin', 'operator', 'builder', 'viewer', 'auditor'])
def test_only_device_managers_can_cancel_a_privileged_emulator_operation(auth_store, app_module, role):
    heartbeat(auth_store.config.dsn, 'worker', 'managed', 'host-one', metrics={'managed_emulators': True})
    store = EmulatorStore(auth_store.config.dsn)
    emulator, _ = store.create_emulator('Managed device', 'host-one', ['chrome'], 'create')
    operation = store.queue_operation(emulator['device_id'], 'start', 'start')
    _, client, _ = signed_in(auth_store, app_module, role)
    result = client.post(f"/runs/{operation['run_id']}/cancel", json={})
    if role in {'admin', 'operator'}:
        assert result.status_code == 200
        assert result.json()['status'] == 'cancelled'
    else:
        assert result.status_code == 403
        assert store.get_run(operation['run_id'])['status'] == 'queued'
