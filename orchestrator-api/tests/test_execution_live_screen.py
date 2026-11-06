"""An execution's live display cannot outlive its exact active Android lease."""
from datetime import datetime, timedelta, timezone
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.access import required_permission
from app.execution_store import ACTIVE, ExecutionStore
from app.live_screen import write_frame
from app.run_models import DeviceRegistration, RunSubmission
from test_authentication import auth_store
from test_live_screen import png
from test_user_roles import signed_in


@pytest.fixture
def active(registered, database_dsn, run_payload, tmp_path, monkeypatch):
    monkeypatch.setenv('EMULYTIX_ARTIFACT_ROOT', str(tmp_path))
    store = ExecutionStore(database_dsn)
    run = store.submit_run(RunSubmission.model_validate(run_payload))
    execution_id = run['executions'][0]['id']
    grant = store.claim(execution_id, 'worker-one', 30)
    with store.connect() as connection:
        started_at = connection.execute('SELECT started_at FROM executions WHERE id=%s', (execution_id,)).fetchone()['started_at']
    return {'store': store, 'id': execution_id, 'grant': grant, 'started_at': started_at,
            'root': tmp_path, 'route': f'/console/executions/{execution_id}/screen'}


def requests(store):
    with store.connect() as connection:
        return connection.execute('SELECT device_id,expires_at FROM live_screen_requests ORDER BY device_id').fetchall()


def test_active_execution_serves_private_frame_and_refreshes_demand_boundedly(active, control_client):
    metadata = write_frame(active['root'], 'phone-1', png(12))
    result = control_client.get(active['route'])
    assert result.status_code == 200, result.text
    assert result.content == png(12)
    assert result.headers['content-type'] == 'image/png'
    assert 'no-store' in result.headers['cache-control']
    assert result.headers['x-screen-frame-id'] == metadata['frame_id']
    assert result.headers['x-screen-captured-at'] == metadata['captured_at']
    before = requests(active['store'])
    assert len(before) == 1 and before[0]['device_id'] == 'phone-1'
    assert control_client.get(active['route']).status_code == 200
    assert requests(active['store']) == before


@pytest.mark.parametrize('status', ACTIVE)
def test_all_active_execution_states_may_display_their_exact_lease(active, control_client, status):
    with active['store'].connect() as connection:
        connection.execute('UPDATE executions SET status=%s WHERE id=%s', (status, active['id']))
    write_frame(active['root'], 'phone-1', png())
    assert control_client.get(active['route']).status_code == 200


@pytest.mark.parametrize('status', ['succeeded', 'failed', 'cancelled', 'needs_review', 'queued'])
def test_terminal_or_queued_execution_never_reads_or_renews_a_screen(active, control_client, monkeypatch, status):
    with active['store'].connect() as connection:
        connection.execute('UPDATE executions SET status=%s WHERE id=%s', (status, active['id']))
        connection.execute("INSERT INTO live_screen_requests(device_id,expires_at) VALUES('phone-1',clock_timestamp()-interval '2 seconds')")
    before = requests(active['store'])
    monkeypatch.setattr('app.screen_routes.read_frame', lambda *_: pytest.fail('inactive execution must not read a frame'))
    assert control_client.get(active['route']).status_code == 410
    assert requests(active['store']) == before


def test_nonexistent_execution_is_404_and_queued_without_a_lease_is_410(registered, database_dsn, run_payload):
    assert registered.get(f'/console/executions/{uuid4()}/screen').status_code == 404
    store = ExecutionStore(database_dsn)
    run = store.submit_run(RunSubmission.model_validate(run_payload))
    assert registered.get(f"/console/executions/{run['executions'][0]['id']}/screen").status_code == 410
    assert requests(store) == []


def test_active_execution_waits_for_its_first_new_frame(active, control_client):
    assert control_client.get(active['route']).status_code == 503
    assert len(requests(active['store'])) == 1
    write_frame(active['root'], 'phone-1', png(), captured_at=active['started_at']-timedelta(milliseconds=100))
    assert control_client.get(active['route']).status_code == 503
    write_frame(active['root'], 'phone-1', png(), captured_at=datetime.now(timezone.utc)-timedelta(seconds=4))
    assert control_client.get(active['route']).status_code == 503


def test_frame_freshness_is_rechecked_before_response_preparation(active, control_client, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, zone):
            return datetime.now(zone)+timedelta(seconds=4)
    write_frame(active['root'], 'phone-1', png())
    monkeypatch.setattr('app.screen_routes.datetime', Clock)
    assert control_client.get(active['route']).status_code == 503
    assert len(requests(active['store'])) == 1


def test_lease_expiring_during_response_preparation_rolls_back_capture_demand(active, control_client, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, zone):
            time.sleep(1.1)
            return datetime.now(zone)
    write_frame(active['root'], 'phone-1', png())
    with active['store'].connect() as connection:
        connection.execute("UPDATE device_leases SET expires_at=clock_timestamp()+interval '1 second' WHERE device_id='phone-1'")
    monkeypatch.setattr('app.screen_routes.datetime', Clock)
    assert control_client.get(active['route']).status_code == 410
    assert requests(active['store']) == []


def test_active_without_a_start_time_is_preparing_without_requesting_capture(active, control_client):
    with active['store'].connect() as connection:
        connection.execute("UPDATE executions SET status='leased',started_at=NULL WHERE id=%s", (active['id'],))
    assert control_client.get(active['route']).status_code == 503
    assert requests(active['store']) == []


@pytest.mark.parametrize('fault', ['missing', 'epoch', 'released', 'expired', 'quarantined', 'execution'])
def test_display_requires_a_live_nonquarantined_lease_for_the_exact_execution(active, control_client, run_payload, fault):
    store = active['store']
    with store.connect() as connection:
        if fault == 'missing':
            connection.execute("DELETE FROM device_leases WHERE device_id='phone-1'")
        elif fault == 'epoch':
            connection.execute("UPDATE device_leases SET lease_epoch=lease_epoch+1 WHERE device_id='phone-1'")
        elif fault == 'released':
            connection.execute("UPDATE device_leases SET owner_id=NULL,execution_id=NULL,expires_at=NULL WHERE device_id='phone-1'")
        elif fault == 'expired':
            connection.execute("UPDATE device_leases SET expires_at=clock_timestamp()-interval '1 second' WHERE device_id='phone-1'")
        elif fault == 'quarantined':
            connection.execute("UPDATE device_leases SET quarantined=true WHERE device_id='phone-1'")
    if fault == 'execution':
        other = store.submit_run(RunSubmission.model_validate({**run_payload, 'idempotency_key':'different-execution'}))
        with store.connect() as connection:
            connection.execute("UPDATE device_leases SET execution_id=%s WHERE device_id='phone-1'", (other['executions'][0]['id'],))
    write_frame(active['root'], 'phone-1', png())
    assert control_client.get(active['route']).status_code == 410
    assert requests(store) == []


@pytest.mark.parametrize('change', ['finished', 'owner', 'epoch', 'expired', 'missing-frame-and-finished'])
def test_execution_is_rechecked_after_reading_and_no_request_is_touched_after_handoff(active, control_client, monkeypatch, change):
    import app.screen_routes as module
    from app.live_screen import ScreenUnavailable
    original = module.read_frame
    write_frame(active['root'], 'phone-1', png())
    if change == 'finished':
        with active['store'].connect() as connection:
            connection.execute("INSERT INTO live_screen_requests(device_id,expires_at) VALUES('phone-1',clock_timestamp()-interval '2 seconds')")
    before = requests(active['store'])
    def during_read(*args):
        result = original(*args)
        if change in {'finished', 'missing-frame-and-finished'}:
            assert active['store'].finish(active['id'], 'worker-one', active['grant']['lease_epoch'], 'succeeded')
        else:
            with active['store'].connect() as connection:
                if change == 'owner':
                    connection.execute("UPDATE device_leases SET owner_id='worker-two' WHERE device_id='phone-1'")
                elif change == 'epoch':
                    connection.execute("UPDATE device_leases SET lease_epoch=lease_epoch+1 WHERE device_id='phone-1'")
                elif change == 'expired':
                    connection.execute("UPDATE device_leases SET expires_at=clock_timestamp()-interval '1 second' WHERE device_id='phone-1'")
        if change == 'missing-frame-and-finished':
            raise ScreenUnavailable('Frame gone')
        return result
    monkeypatch.setattr(module, 'read_frame', during_read)
    assert control_client.get(active['route']).status_code == 410
    assert requests(active['store']) == before


def test_exact_case_sensitive_device_identity_selects_the_matching_display(active, control_client, run_payload):
    store = active['store']
    store.register_device(DeviceRegistration(device_id='Phone-1',host_id='host-1',serial='SerialABC',kind='physical'))
    other = store.submit_run(RunSubmission.model_validate({**run_payload,'device_ids':['Phone-1'],'idempotency_key':'case-sensitive-device'}))
    assert store.claim(other['executions'][0]['id'], 'worker-two', 30)
    write_frame(active['root'], 'Phone-1', png(99))
    write_frame(active['root'], 'phone-1', png(12))
    result = control_client.get(active['route'])
    assert result.status_code == 200 and result.content == png(12)
    assert [row['device_id'] for row in requests(store)] == ['phone-1']


@pytest.mark.parametrize('role', ['admin','builder','operator','viewer','auditor'])
def test_display_requires_current_runs_read_permission_and_session(active, auth_store, app_module, role):
    user, client, _ = signed_in(auth_store, app_module, role)
    write_frame(active['root'], 'phone-1', png())
    assert required_permission('GET',active['route']) == 'runs.read'
    assert required_permission('HEAD',active['route']) == 'runs.read'
    for method in ['POST','PATCH','DELETE','PUT']:
        assert required_permission(method,active['route']) is None
        assert client.request(method,active['route'],json={}).status_code == 403
    assert client.get(active['route']).status_code == 200
    with auth_store.connect() as connection:
        connection.execute('DELETE FROM auth_sessions WHERE user_id=%s', (user['id'],))
    before = requests(active['store'])
    assert client.get(active['route']).status_code == 401
    assert client.get(f'/console/executions/{uuid4()}/screen').status_code == 401
    assert requests(active['store']) == before
    with TestClient(app_module.app) as anonymous:
        assert anonymous.get(active['route']).status_code == 401
