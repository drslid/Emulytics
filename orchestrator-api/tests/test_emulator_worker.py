import base64
from uuid import uuid4

import pytest
from fastapi import HTTPException
from psycopg.types.json import Jsonb

from app.android_driver import AndroidDriver
from app.emulator_runtime import adb_server
from app.emulator_store import EmulatorStore
from app.worker import Worker

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=')


@pytest.mark.parametrize('application_ids,expected_state', [
    (['chrome'], 'ready'),
    (['chrome', 'snapchat', 'linkedin', 'instagram', 'tiktok'], 'running'),
    (['chrome', 'uploaded'], 'running'),
])
def test_managed_power_and_journey_share_the_same_lease_queue(registered, run_payload, database_dsn, tmp_path, monkeypatch, application_ids, expected_state):
    store = EmulatorStore(database_dsn)
    with store.connect() as connection:
        connection.execute("INSERT INTO service_heartbeats(component,instance_id,status,host_id,metrics) VALUES('worker','managed-test','ready','host-1',%s)", (Jsonb({'managed_emulators': True}),))
    missing_upload = 'uploaded' in application_ids
    if missing_upload:
        app_id = str(uuid4())
        store.add_application({'id': app_id, 'filename': app_id + '.apk', 'sha256': 'a' * 64,
                               'package_name': 'com.example.demo', 'name': 'Demo', 'size_bytes': 1})
        application_ids = ['chrome', app_id]
    emulator, _ = store.create_emulator('Prepared phone', 'host-1', application_ids, str(uuid4()))
    run = store.queue_operation(emulator['device_id'], 'start', str(uuid4()))
    monkeypatch.setenv('EMULYTIX_MANAGED_EMULATORS', 'true')
    starts = []

    class Driver(AndroidDriver):
        def __init__(self, *args, **kwargs):
            assert kwargs['adb_server_host'] == adb_server(emulator)
            super().__init__(*args, **kwargs)

        def command(self, args, *, effect, **kwargs):
            assert args[0] != 'install', 'Power-on must never install an application'
            self.before_command(['adb', '-s', self.serial, *args], effect)
            self.poll()
            if self.after_command:
                self.after_command('done', {'returncode': 0})
            if args[:3] == ['shell', 'pm', 'path']:
                return 'package:/system/app/Chrome/Chrome.apk\n'
            if args[:4] == ['shell', 'pm', 'list', 'packages']:
                return 'package:com.android.chrome\n' if len(args) == 4 or args[4] == 'com.android.chrome' else ''
            if args[:2] == ['shell', 'dumpsys']:
                return 'mCurrentFocus=Window{0 u0 com.android.launcher3/Launcher}'
            if args[:3] == ['shell', 'uiautomator', 'dump']:
                return f'UI hierarchy dumped to: {args[-1]}\n'
            if args[:2] == ['shell', 'cat']:
                return '<hierarchy />'
            return PNG if kwargs.get('binary') else 'ok\n'

    from app.emulator_runtime import EmulatorRuntime

    class Runtime(EmulatorRuntime):
        def __init__(self, record, driver):
            self.record, self.driver = record, driver
        def start(self):
            self.driver.before_command(['docker', 'start-container'], True)
            starts.append(self.record['id'])
            self.driver.after_command('done', {'operation': 'start-container'})
            return {'boot_completed': True}
        def stop(self):
            self.driver.before_command(['docker', 'stop-container'], True)
            self.driver.after_command('done', {'operation': 'stop-container'})
            return {'data_retained': True}
        def close(self):
            pass

    monkeypatch.setattr('app.emulator_runtime.EmulatorRuntime', Runtime)
    worker = Worker(database_dsn, 'host-1', lock_root=tmp_path / 'locks', artifact_root=tmp_path / 'artifacts', driver_factory=Driver)
    assert worker.run_once()
    assert store.get_run(run['run_id'])['status'] == 'succeeded'
    ready = store.managed_device(emulator['device_id'])
    assert ready['state'] == expected_state and ready['installed_packages'] == ['com.android.chrome']
    journey = registered.post('/runs', json={**run_payload, 'device_ids': [emulator['device_id']], 'idempotency_key': str(uuid4())})
    if expected_state == 'ready':
        assert journey.status_code == 202
        with pytest.raises(HTTPException) as busy:
            store.queue_operation(emulator['device_id'], 'stop', str(uuid4()))
        assert busy.value.status_code == 409
        assert worker.run_once()
        assert store.get_run(journey.json()['id'])['status'] == 'succeeded'
    else:
        assert journey.status_code == 409
        if not missing_upload:
            with pytest.raises(HTTPException) as unavailable:
                store.queue_operation(emulator['device_id'], 'prepare', str(uuid4()))
            assert unavailable.value.status_code == 422
    stop = store.queue_operation(emulator['device_id'], 'stop', str(uuid4()))
    assert worker.run_once()
    assert store.get_run(stop['run_id'])['status'] == 'succeeded'
    assert store.managed_device(emulator['device_id'])['state'] == 'stopped'
    assert store.managed_device(emulator['device_id'])['installed_packages'] == ['com.android.chrome']
    restart = store.queue_operation(emulator['device_id'], 'start', str(uuid4()))
    assert worker.run_once()
    assert store.get_run(restart['run_id'])['status'] == 'succeeded'
    assert store.managed_device(emulator['device_id'])['state'] == expected_state
    assert starts == [emulator['id'], emulator['id']]
