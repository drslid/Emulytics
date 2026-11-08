import hashlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from docker.errors import NotFound
from requests.exceptions import ReadTimeout

from app.android_driver import DriverError
from app.emulator_runtime import BOOT_COMMAND, EmulatorRuntime, RuntimeUncertain, application_is_prepared, container_name, prepare_application


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
    assert '-data "$ANDROID_AVD_HOME/emulytix-managed.avd/userdata-qemu.img"' in BOOT_COMMAND


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


@pytest.mark.parametrize('digest,installed,expected', [
    (None, False, False),
    ('a' * 64, False, False),
    ('a' * 64, True, True),
    ('b' * 64, True, False),
])
def test_power_on_checks_apk_readiness_without_reading_or_installing_an_artifact(digest, installed, expected):
    driver = Driver()
    def command(args, *, effect):
        assert effect is False
        driver.commands.append(args)
        if args == ['shell', 'pm', 'list', 'packages', 'com.example.demo']:
            return 'package:com.example.demo\n' if installed else ''
        if args == ['shell', 'pm', 'path', 'com.example.demo']:
            assert installed
            return 'package:/data/app/com.example.demo-X==/base.apk\n'
        assert args == ['shell', 'sha256sum', '/data/app/com.example.demo-X==/base.apk']
        return 'a' * 64 + '  /data/app/com.example.demo-X==/base.apk\n'
    driver.command = command
    application = {'source': 'apk', 'package_name': 'com.example.demo', 'sha256': digest}
    assert application_is_prepared(driver, application) is expected
    if digest is None:
        assert not driver.commands


@pytest.mark.parametrize('observed,expected', [
    ('package:com.android.chrome\n', True),
    ('package:com.android.chrome.beta\n', False),
    ('', False),
])
def test_power_on_verifies_the_exact_system_package(observed, expected):
    driver = Driver()
    def command(args, *, effect):
        assert args == ['shell', 'pm', 'list', 'packages', 'com.android.chrome']
        assert effect is False
        return observed
    driver.command = command
    assert application_is_prepared(driver, {'source': 'system', 'package_name': 'com.android.chrome'}) is expected


@pytest.mark.parametrize('package', ['com.example; reboot', None])
def test_power_on_rejects_invalid_packages_before_using_adb(package):
    driver = Driver()
    with pytest.raises(DriverError, match='Invalid application package'):
        application_is_prepared(driver, {'source': 'apk', 'package_name': package})
    assert not driver.commands


def hardware_container(runtime, *, running=False, matching=True):
    labels = {**runtime.labels}
    if matching:
        labels['emulytix.hardware'] = runtime.hardware_hash
    return {'Config': {'Labels': labels}, 'Mounts': [{'Name': runtime.volume_name,
            'Destination': '/managed', 'Type': 'volume'}], 'HostConfig': {},
            'NetworkSettings': {'Networks': {runtime.network: {}}}, 'State': {'Running': running}}


def hardware_driver(driver, width=720, height=1280, density=320, blocks=8125880):
    def command(args, **options):
        driver.commands.append(args)
        return {('shell', 'getprop', 'sys.boot_completed'): '1\n',
                ('shell', 'wm', 'size'): f'Physical size: {width}x{height}\n',
                ('shell', 'wm', 'density'): f'Physical density: {density}\n',
                ('shell', 'df', '-k', '/data'): f'Filesystem 1K-blocks Used Available Use% Mounted on\n/dev/block/vdc {blocks} 62212 7916212 1% /data\n'}[tuple(args)]
    driver.command = command


def test_changed_hardware_replaces_only_owned_stopped_container_and_retains_volume():
    from app.emulator_hardware import DEFAULT_HARDWARE
    driver = Driver()
    hardware_driver(driver)
    runtime = EmulatorRuntime({**record(), 'hardware': DEFAULT_HARDWARE}, driver, client=SimpleNamespace())
    removed, created, volumes = [], [], []
    stopped = SimpleNamespace(attrs=hardware_container(runtime, matching=False), remove=lambda **options: removed.append(options))
    new = SimpleNamespace(attrs=hardware_container(runtime), start=lambda: None)
    runtime.client.containers = SimpleNamespace(get=lambda name: stopped,
        create=lambda *args, **options: created.append(options) or new)
    runtime.client.networks = SimpleNamespace(get=lambda name: SimpleNamespace(attrs={'Labels': {'emulytix.bench': 'wf01'}}))
    runtime.client.images = SimpleNamespace(get=lambda name: None)
    runtime.client.volumes = SimpleNamespace(get=lambda name: volumes.append(name) or SimpleNamespace(attrs={'Labels': runtime.labels}))
    applied = runtime.start(timeout=0.2)['applied_hardware']
    assert applied == {**{key:value for key,value in DEFAULT_HARDWARE.items() if key!='storage_gb'},'storage_capacity_bytes':8125880*1024}
    assert removed == [{'v': False, 'force': False}]
    assert volumes == [runtime.volume_name]
    assert created[0]['volumes'] == {runtime.volume_name: {'bind': '/managed', 'mode': 'rw'}}
    assert created[0]['environment']['EMULYTIX_STORAGE_GB'] == '8'
    assert created[0]['environment']['EMULYTIX_RAM_MB'] == '1536'
    assert created[0]['nano_cpus'] == 2_000_000_000 and created[0]['mem_limit'] == '3072m'


def test_running_container_is_never_replaced_to_apply_different_hardware():
    from app.emulator_hardware import DEFAULT_HARDWARE
    driver = Driver()
    runtime = EmulatorRuntime({**record(), 'hardware': DEFAULT_HARDWARE}, driver, client=SimpleNamespace())
    existing = SimpleNamespace(attrs=hardware_container(runtime, running=True, matching=False))
    runtime.client.containers = SimpleNamespace(get=lambda name: existing)
    with pytest.raises(DriverError, match='Stop the emulator'):
        runtime.start(timeout=0.2)
    assert not driver.journal


def test_running_matching_hardware_is_verified_against_android_display():
    from app.emulator_hardware import DEFAULT_HARDWARE
    driver = Driver()
    hardware_driver(driver, width=1080, height=1920)
    runtime = EmulatorRuntime({**record(), 'hardware': DEFAULT_HARDWARE}, driver, client=SimpleNamespace())
    existing = SimpleNamespace(attrs=hardware_container(runtime, running=True))
    runtime.client.containers = SimpleNamespace(get=lambda name: existing)
    with pytest.raises(DriverError, match='does not match'):
        runtime.start(timeout=0.2)
    assert not driver.journal


@pytest.mark.parametrize('blocks',[6000000,8125880])
def test_effective_storage_comes_from_android_instead_of_default_or_legacy_requested_size(blocks):
    from app.emulator_hardware import DEFAULT_HARDWARE
    driver = Driver()
    hardware_driver(driver, blocks=blocks)
    runtime = EmulatorRuntime({**record(),'hardware':DEFAULT_HARDWARE}, driver, client=SimpleNamespace())
    runtime.client.containers = SimpleNamespace(get=lambda name:SimpleNamespace(attrs=hardware_container(runtime,running=True)))
    applied = runtime.start(timeout=0.2)['applied_hardware']
    assert 'storage_gb' not in applied
    assert applied['storage_capacity_bytes'] == blocks*1024


def test_unreadable_storage_stays_unknown_after_successful_display_verification():
    from app.emulator_hardware import DEFAULT_HARDWARE
    driver = Driver()
    hardware_driver(driver)
    original = driver.command
    def command(args, **options):
        if args==['shell','df','-k','/data']:
            raise DriverError('df unavailable')
        return original(args,**options)
    driver.command = command
    runtime = EmulatorRuntime({**record(),'hardware':DEFAULT_HARDWARE}, driver, client=SimpleNamespace())
    runtime.client.containers = SimpleNamespace(get=lambda name:SimpleNamespace(attrs=hardware_container(runtime,running=True)))
    applied = runtime.start(timeout=0.2)['applied_hardware']
    assert applied['storage_capacity_bytes'] is None and 'storage_gb' not in applied


def test_power_off_flushes_guest_data_before_stopping_and_retains_named_volume():
    driver = Driver()
    runtime = EmulatorRuntime(record(), driver, client=SimpleNamespace())
    attrs = hardware_container(runtime, running=True, matching=False)
    def stop(**options):
        assert driver.commands == [['shell','sync']]
        attrs['State']['Running'] = False
    container = SimpleNamespace(attrs=attrs, stop=stop, reload=lambda: None)
    runtime.client.containers = SimpleNamespace(get=lambda name: container)
    result = runtime.stop()
    assert result['guest_sync_confirmed'] is True and result['data_retained'] is True


def test_offline_guest_can_still_be_stopped_but_durability_is_not_claimed():
    driver = Driver()
    runtime = EmulatorRuntime(record(), driver, client=SimpleNamespace())
    attrs = hardware_container(runtime, running=True, matching=False)
    def offline(*args, **options):
        raise DriverError('adb offline')
    driver.command = offline
    def stop(**options):
        attrs['State']['Running'] = False
    runtime.client.containers = SimpleNamespace(get=lambda name: SimpleNamespace(attrs=attrs,stop=stop,reload=lambda: None))
    assert runtime.stop()['guest_sync_confirmed'] is False
