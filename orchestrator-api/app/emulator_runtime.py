"""Worker-only management of fixed, owned Android containers and persistent AVDs."""

import hashlib
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shlex
import time
from uuid import UUID, uuid4

import docker
from docker.errors import DockerException, NotFound
from requests.exceptions import RequestException

from .android_driver import DriverError
from .emulator_hardware import applied_profile, hardware_config

BOOT_COMMAND = r'''
set -euo pipefail
mkdir -p "$ANDROID_AVD_HOME"
if [ ! -f "$ANDROID_AVD_HOME/emulytix-managed.ini" ]; then
  echo no | avdmanager create avd --name emulytix-managed \
    --package 'system-images;android-29;google_apis;x86_64'
fi
if [ -n "${EMULYTIX_RAM_MB:-}" ]; then
  config="$ANDROID_AVD_HOME/emulytix-managed.avd/config.ini"
  sed -i -E '/^(hw\.lcd\.(width|height|density)|hw\.ramSize|hw\.cpu\.ncore|skin\.(name|path))=/d' "$config"
  printf '%s\n' "hw.lcd.width=$EMULYTIX_WIDTH" "hw.lcd.height=$EMULYTIX_HEIGHT" \
    "hw.lcd.density=$EMULYTIX_DENSITY" "hw.ramSize=$EMULYTIX_RAM_MB" \
    "hw.cpu.ncore=$EMULYTIX_CPU_CORES" "skin.name=${EMULYTIX_WIDTH}x${EMULYTIX_HEIGHT}" >> "$config"
  # Existing userdata is never resized or wiped when replacing a stopped container.
  if ! compgen -G "$ANDROID_AVD_HOME/emulytix-managed.avd/userdata-qemu.img*" > /dev/null; then
    sed -i '/^disk\.dataPartition\.size=/d' "$config"
    printf '%s\n' "disk.dataPartition.size=${EMULYTIX_STORAGE_GB}G" >> "$config"
  fi
fi
adb -a -P 5037 nodaemon server > /tmp/adb-server.log 2>&1 &
adb_pid=$!
for attempt in $(seq 1 50); do
  if (: > /dev/tcp/127.0.0.1/5037) 2>/dev/null; then break; fi
  kill -0 "$adb_pid"
  sleep 0.1
done
/opt/android-sdk/emulator/emulator -avd emulytix-managed -no-window -no-audio \
  -no-boot-anim -no-snapshot -gpu swiftshader_indirect -memory "${EMULYTIX_RAM_MB:-1536}" -cores "${EMULYTIX_CPU_CORES:-2}" \
  -data "$ANDROID_AVD_HOME/emulytix-managed.avd/userdata-qemu.img" \
  -port "$EMULYTIX_EMULATOR_PORT" -accel on > /tmp/emulator.log 2>&1 &
emulator_pid=$!
trap 'kill -TERM "$emulator_pid" 2>/dev/null || true; wait "$emulator_pid" || true; exit 0' TERM INT
wait -n
'''


class RuntimeUncertain(RuntimeError):
    """A Docker daemon may have accepted the action; never release its reservation."""


def container_name(record) -> str:
    return 'emulytix-managed-' + UUID(str(record['id'])).hex


def adb_server(record) -> str:
    return container_name(record)


class EmulatorRuntime:
    def __init__(self, record, driver, *, client=None):
        self.record, self.driver = record, driver
        self.name = container_name(record)
        self.volume_name = 'emulytix-avd-' + UUID(str(record['id'])).hex
        self.labels = {'emulytix.managed': 'console-v1', 'emulytix.emulator': str(record['id']),
                       'emulytix.host': record['host_id']}
        self.hardware = hardware_config(record['hardware']) if 'hardware' in record else None
        if self.hardware is not None:
            from .run_store import fingerprint
            self.hardware_hash = fingerprint({'hardware':self.hardware,'boot_command':BOOT_COMMAND})
        else:
            self.hardware_hash = None
        self.image = os.getenv('EMULYTIX_MANAGED_IMAGE', 'emulytix/android-runtime:0.9.0')
        self.network = os.getenv('EMULYTIX_BENCH_NETWORK', 'emulytix-wf01-bench')
        self.client = client or docker.from_env(timeout=5)
        self.owns_client = client is None

    def _owned(self, labels):
        if any((labels or {}).get(key) != value for key, value in self.labels.items()):
            raise DriverError('Emulator resource ownership could not be verified')

    def _effect(self, operation, call):
        self.driver.before_command(['docker', operation], True)
        status = 'uncertain'
        try:
            result = call()
            self.driver.poll()
            status = 'done'
            return result
        except (DockerException, RequestException):
            raise RuntimeUncertain('Emulator container operation requires review') from None
        finally:
            if self.driver.after_command:
                self.driver.after_command(status, {'operation': operation})

    def _container(self):
        self.driver.poll()
        try:
            container = self.client.containers.get(self.name)
        except NotFound:
            return None
        attrs = container.attrs
        self._owned(attrs.get('Config', {}).get('Labels'))
        mounts = attrs.get('Mounts', [])
        if (not any(m.get('Name') == self.volume_name and m.get('Destination') == '/managed'
                    and m.get('Type') == 'volume' for m in mounts)
                or set(attrs.get('NetworkSettings', {}).get('Networks', {})) != {self.network}
                or attrs.get('HostConfig', {}).get('Privileged')
                or attrs.get('HostConfig', {}).get('PortBindings')):
            raise DriverError('Emulator resource configuration does not match')
        return container

    def start(self, timeout=180):
        container = self._container()
        if container is not None and self.hardware_hash is not None:
            applied = container.attrs.get('Config', {}).get('Labels', {}).get('emulytix.hardware')
            if applied != self.hardware_hash:
                if container.attrs.get('State', {}).get('Running'):
                    raise DriverError('Stop the emulator before applying its new hardware configuration')
                # Ownership and the persistent volume were verified by _container.
                self._effect('replace-stopped-container', lambda: container.remove(v=False, force=False))
                container = None
        if container is None:
            network = self.client.networks.get(self.network)
            if network.attrs.get('Labels', {}).get('emulytix.bench') != 'wf01':
                raise DriverError('Managed emulator network is not available')
            self.client.images.get(self.image)  # Never pull an image selected through the browser.
            try:
                volume = self.client.volumes.get(self.volume_name)
                self._owned(volume.attrs.get('Labels'))
            except NotFound:
                self._effect('create-volume', lambda: self.client.volumes.create(self.volume_name, labels=self.labels))
            port = 5554 + int(self.record['slot']) * 2
            if not 5556 <= port <= 5562 or self.record['serial'] != f'emulator-{port}':
                raise DriverError('Invalid managed emulator slot')
            environment = {'ANDROID_AVD_HOME': '/managed/avd', 'EMULYTIX_EMULATOR_PORT': str(port)}
            labels = dict(self.labels)
            if self.hardware is not None:
                environment.update({'EMULYTIX_'+key.upper(): str(value) for key,value in self.hardware.items()})
                labels['emulytix.hardware'] = self.hardware_hash
            container = self._effect('create-container', lambda: self.client.containers.create(
                self.image, ['-lc', BOOT_COMMAND], name=self.name, network=self.network,
                entrypoint=['/bin/bash'], environment=environment,
                labels=labels, volumes={self.volume_name: {'bind': '/managed', 'mode': 'rw'}},
                devices=['/dev/kvm:/dev/kvm:rwm'], mem_limit=f'{max(3072,self.hardware["ram_mb"]+1024) if self.hardware else 3072}m',
                nano_cpus=(self.hardware['cpu_cores'] if self.hardware else 2)*1_000_000_000,
                shm_size='256m', init=True, security_opt=['no-new-privileges:true'],
                restart_policy={'Name': 'unless-stopped'},
            ))
        if not container.attrs.get('State', {}).get('Running'):
            self._effect('start-container', container.start)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.driver.poll()
            try:
                booted = self.driver.command(['shell', 'getprop', 'sys.boot_completed'], effect=False, timeout_s=3)
            except DriverError:
                self.driver.poll()
                booted = ''
            if booted.strip() == '1':
                evidence = {'state': 'running', 'boot_completed': True}
                if self.hardware is not None:
                    size = self.driver.command(['shell','wm','size'], effect=False)
                    density = self.driver.command(['shell','wm','density'], effect=False)
                    if (not re.search(rf'Physical size:\s*{self.hardware["width"]}x{self.hardware["height"]}\b',size)
                            or not re.search(rf'Physical density:\s*{self.hardware["density"]}\b',density)):
                        raise DriverError('Android display does not match the requested hardware configuration')
                    capacity = None
                    try:
                        observed = self.driver.command(['shell','df','-k','/data'], effect=False, timeout_s=5)
                        for line in observed.splitlines():
                            fields = line.split()
                            if len(fields)==6 and fields[-1]=='/data' and fields[1].isdigit():
                                capacity = int(fields[1])*1024
                                break
                    except DriverError:
                        self.driver.poll()
                    evidence['applied_hardware'] = applied_profile({**self.hardware,'storage_capacity_bytes':capacity})
                return evidence
            time.sleep(0.25)
        raise DriverError('Android did not finish booting within three minutes')

    def stop(self):
        container = self._container()
        synced = None
        if container is not None and container.attrs.get('State', {}).get('Running'):
            try:
                # Flush guest writes before TERM; retaining the volume alone misses dirty guest pages.
                self.driver.command(['shell','sync'], effect=True, timeout_s=10)
                synced = True
            except DriverError:
                self.driver.poll()
                synced = False
            # Graceful TERM reaches the emulator; its named userdata volume is retained.
            self._effect('stop-container', lambda: container.stop(timeout=20))
            container.reload()
            self.driver.poll()
            if container.attrs.get('State', {}).get('Running'):
                raise RuntimeUncertain('Emulator stop could not be confirmed')
        return {'state': 'stopped', 'data_retained': True, 'guest_sync_confirmed': synced}

    def close(self):
        if self.owns_client:
            self.client.close()

    def execute_step(self, step):
        if step['id'] == 'runtime':
            evidence = self.stop() if self.record['action'] == 'stop' else self.start()
        else:
            index = int(step['id'].split('-')[1]) - 1
            evidence = prepare_application(self.driver, self.record['applications'][index])
        evidence = {**evidence, 'assertion_passed': True}
        if self.record['action'] != 'stop':
            from .live_screen import valid_png
            image = self.driver.command(['exec-out', 'screencap', '-p'], effect=False, binary=True)
            if not valid_png(image):
                raise DriverError('Android preparation capture is unavailable')
            self.driver.artifact_dir.mkdir(parents=True, exist_ok=True)
            target = self.driver.artifact_dir / (uuid4().hex + '.png')
            target.write_bytes(image)
            evidence.update(screenshot=str(target), screenshot_sha256=hashlib.sha256(image).hexdigest(),
                            captured_at=datetime.now(timezone.utc).isoformat())
        return evidence


def installed_digest(driver, package):
    # `pm path` exits with 1 for a missing app; absence is expected before installation.
    present = driver.command(['shell', 'pm', 'list', 'packages', package], effect=False)
    if f'package:{package}' not in present.splitlines():
        return None
    paths = driver.command(['shell', 'pm', 'path', package], effect=False)
    for line in paths.splitlines():
        if line.startswith('package:') and line.endswith('/base.apk'):
            path = line[len('package:'):]
            if not re.fullmatch(r'/[A-Za-z0-9_./+=~\-]+', path):
                raise DriverError('Installed application path could not be verified')
            result = driver.command(['shell', 'sha256sum', shlex.quote(path)], effect=False)
            if re.match(r'^[a-fA-F0-9]{64}\s', result):
                return result[:64].lower()
    return None


def _application_package(application):
    package = application['package_name']
    if not isinstance(package,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+', package):
        raise DriverError('Invalid application package')
    return package


def application_is_prepared(driver, application):
    """Power-on verifies selected apps without ever installing or updating one."""
    package = _application_package(application)
    if application['source'] == 'system':
        if package != 'com.android.chrome':
            return False
        observed = driver.command(['shell','pm','list','packages',package],effect=False)
        return f'package:{package}' in observed.splitlines()
    digest = application.get('sha256')
    if not isinstance(digest,str) or not re.fullmatch(r'[a-f0-9]{64}',digest):
        return False
    return installed_digest(driver,package) == digest


def prepare_application(driver, application):
    package = _application_package(application)
    if application['source'] == 'system':
        if package != 'com.android.chrome' or not driver.command(
                ['shell', 'pm', 'path', package], effect=False).strip().startswith('package:'):
            raise DriverError('Chrome is missing from the managed Android image')
        return {'package': package, 'verified': True, 'installed': False}
    filename, digest = application.get('filename'), application.get('sha256')
    if (not driver.apk_dir or not isinstance(filename, str)
            or not re.fullmatch(r'[a-f0-9-]{36}\.apk', filename)
            or not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest)):
        raise DriverError('A verified APK must be imported before preparation')
    artifact = driver.apk_dir / filename
    if artifact.is_symlink() or not artifact.is_file() or artifact.resolve().parent != driver.apk_dir.resolve():
        raise DriverError('Application artifact is unavailable')
    with artifact.open('rb') as handle:
        if hashlib.file_digest(handle, 'sha256').hexdigest() != digest:
            raise DriverError('Application artifact checksum does not match')
    installed = installed_digest(driver, package) != digest
    if installed:
        driver.command(['install', '-r', str(artifact)], effect=True, timeout_s=120)
    if installed_digest(driver, package) != digest:
        raise DriverError('Installed application checksum could not be confirmed')
    return {'package': package, 'sha256': digest, 'verified': True, 'installed': installed}
