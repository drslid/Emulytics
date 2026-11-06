import hashlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from docker.errors import NotFound
from requests.exceptions import ReadTimeout

from app.android_driver import DriverError
from app.emulator_runtime import BOOT_COMMAND, EmulatorRuntime, RuntimeUncertain, container_name, prepare_application


def record():
    return {'id': uuid4(), 'host_id': 'host-1', 'serial': 'emulator-5556', 'slot': 1}


class Driver:
    def __init__(self, apk_dir=None):
        self.apk_dir = apk_dir
        self.journal = []
        self.before_command = lambda argv, effect: self.journal.append((argv, effect))
        self.after_command = lambda status, evidence: self.journal.append(status)
        self.commands = []

    def poll(self):
        pass

    def command(self, argv, **options):
        self.commands.append(argv)
        return '1\n'


def test_owned_stopped_container_is_restarted_without_recreating_userdata():
    data, driver = record(), Driver()
    runtime = EmulatorRuntime(data, driver, client=SimpleNamespace())
    attrs = {'Config': {'Labels': runtime.labels}, 'Mounts': [{'Name': runtime.volume_name,
             'Destination': '/managed', 'Type': 'volume'}],
             'NetworkSettings': {'Networks': {runtime.network: {}}}, 'State': {'Running': False}}
    starts = []
    container = SimpleNamespace(attrs=attrs, start=lambda: starts.append(True))
    runtime.client.containers = SimpleNamespace(get=lambda name: container)
    assert runtime.start(timeout=0.1)['boot_completed']
    assert starts == [True]
    assert driver.journal[0] == (['docker', 'start-container'], True)
    assert 'avdmanager create' in BOOT_COMMAND and '--force' not in BOOT_COMMAND
    assert 'if [ ! -f' in BOOT_COMMAND and '-wipe-data' not in BOOT_COMMAND


def test_container_name_collision_without_ownership_never_starts_or_stops():
    data, driver = record(), Driver()
    container = SimpleNamespace(attrs={'Config': {'Labels': {}}, 'State': {'Running': True}})
    client = SimpleNamespace(containers=SimpleNamespace(get=lambda name: container))
    runtime = EmulatorRuntime(data, driver, client=client)
    with pytest.raises(DriverError, match='ownership'):
        runtime.stop()
    assert not driver.journal


def test_daemon_timeout_is_uncertain_and_keeps_an_unconfirmed_action():
    driver = Driver()
    runtime = EmulatorRuntime(record(), driver, client=SimpleNamespace())
    def timeout():
        raise ReadTimeout('daemon may have started the container')
    with pytest.raises(RuntimeUncertain):
        runtime._effect('start-container', timeout)
    assert driver.journal[-1] == 'uncertain'


def test_artifact_hash_is_checked_before_any_installation(tmp_path):
    filename = str(uuid4()) + '.apk'
    (tmp_path / filename).write_bytes(b'tampered')
    driver = Driver(tmp_path)
    application = {'source': 'apk', 'package_name': 'com.example.demo', 'filename': filename,
                   'sha256': hashlib.sha256(b'approved').hexdigest()}
    with pytest.raises(DriverError, match='checksum'):
        prepare_application(driver, application)
    assert not driver.commands


def test_prepared_apk_is_compared_to_installed_base_apk_before_and_after_install(tmp_path):
    filename = str(uuid4()) + '.apk'
    data = b'approved-apk'; digest = hashlib.sha256(data).hexdigest()
    (tmp_path / filename).write_bytes(data)
    driver = Driver(tmp_path)
    installed = []
    def command(args, **kw):
        driver.commands.append(args)
        if args[:4] == ['shell', 'pm', 'list', 'packages']:
            return 'package:com.example.demo\n' if installed else ''
        if args[:3] == ['shell', 'pm', 'path']:
            if not installed:
                raise DriverError('pm path exits 1 when the package is absent')
            return 'package:/data/app/com.example.demo-X==/base.apk\n'
        if args[:2] == ['shell', 'sha256sum']:
            return digest + '  /data/app/com.example.demo-X==/base.apk\n'
        assert args == ['install', '-r', str(tmp_path / filename)] and kw['effect'] is True
        installed.append(True)
        return 'Success\n'
    driver.command = command
    application = {'source': 'apk', 'package_name': 'com.example.demo', 'filename': filename, 'sha256': digest}
    assert prepare_application(driver, application)['installed'] is True
    assert prepare_application(driver, application)['installed'] is False
    assert len(installed) == 1
