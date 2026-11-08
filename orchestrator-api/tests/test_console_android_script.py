"""Exercise the launcher contract without starting Docker or touching a real console."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


LAUNCHER = Path(__file__).resolve().parents[2] / 'scripts/start-console-android.sh'
FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, sys, types
from contextlib import contextmanager
from pathlib import Path
args = sys.argv[1:]
log = Path(os.environ['FAKE_DOCKER_LOG'])
def record(event, **values):
    with log.open('a') as output:
        output.write(json.dumps(dict(event=event, **values)) + '\n')
record('docker', args=args, host=os.getenv('EMULYTIX_HOST_ID'), adb=os.getenv('ADB_SERVER_SOCKET'))
if args[0] == 'compose':
    if 'ps' in args:
        if os.getenv('FAKE_BASE', 'true') == 'true': print('existing-console-container')
    elif 'up' in args:
        pass
    elif 'exec' in args:
        source = sys.stdin.read()
        if 'console-api' in args:
            class Connection:
                def execute(self, query, params):
                    assert query.startswith('SELECT device_id FROM devices WHERE host_id=')
                    assert params == ('bench-host', 'emulator-5554')
                    return self
                def fetchone(self):
                    return {'device_id': 'existing-device'} if os.getenv('FAKE_DEVICE') else None
            class RunStore:
                def __init__(self, dsn): pass
                @contextmanager
                def connect(self): yield Connection()
                def register_device(self, payload):
                    record('registered', fields=vars(payload))
                    return vars(payload), True
            store_module = types.ModuleType('app.run_store'); store_module.RunStore = RunStore
            model_module = types.ModuleType('app.run_models'); model_module.DeviceRegistration = lambda **fields: types.SimpleNamespace(**fields)
            sys.modules['app'] = types.ModuleType('app')
            sys.modules['app.run_store'] = store_module; sys.modules['app.run_models'] = model_module
            import urllib.request
            class Health:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *args): pass
            urllib.request.urlopen = lambda *args, **kwargs: Health()
            os.environ['EMULYTIX_DATABASE_URL'] = 'test-only'
            exec(source)
        elif 'console-worker' in args:
            assert "'emulator-5554'" in source
        else: sys.exit(3)
    else: sys.exit(4)
elif args[:2] == ['container', 'inspect']:
    sys.exit(0 if os.getenv('FAKE_CONTAINER', 'true') == 'true' or Path(os.environ['FAKE_CREATED']).exists() else 1)
elif args[:2] == ['network', 'inspect']:
    print('wf01')
elif args[0] == 'inspect':
    fmt = args[args.index('--format') + 1]
    if 'emulytix.bench.persistence' in fmt: print(os.getenv('FAKE_PERSISTENCE', 'preserve-avd-v1'))
    elif '.Config.Labels' in fmt: print(os.getenv('FAKE_LABEL', 'wf01'))
    elif '.Config.Entrypoint' in fmt: print(os.getenv('FAKE_ENTRYPOINT', '["/bin/bash"]'))
    elif '.Config.Cmd' in fmt:
        mode = os.getenv('FAKE_COMMAND', 'safe')
        safe = 'if [[ ! -f "$ANDROID_AVD_HOME/emulytix-wf01.ini" ]]; then\n echo no | avdmanager create avd --name emulytix-wf01\nfi'
        if mode == 'safe': print(json.dumps(['-lc', safe]))
        elif mode == 'legacy': print(json.dumps(['-lc', 'echo no | avdmanager create avd --force --name emulytix-wf01']))
        elif mode == 'guarded-force': print(json.dumps(['-lc', safe + '\n avdmanager create avd --force --name emulytix-wf01']))
        elif mode == 'wipe-data': print(json.dumps(['-lc', safe + '\n emulator -wipe-data']))
        elif mode == 'unknown': print(json.dumps(['-lc', 'custom boot command']))
        elif mode == 'wrong-shape': print(json.dumps({'unexpected':'object'}))
        else: print('unreadable')
    elif '.State.Running' in fmt: print(os.getenv('FAKE_RUNNING', 'true'))
    elif '.NetworkSettings.Networks' in fmt: print('emulytix-wf01-bench')
    else: sys.exit(5)
elif args[0] == 'exec':
    print(os.getenv('FAKE_BOOT', '1'))
elif args[0] == 'start':
    pass
else: sys.exit(6)
'''


@pytest.fixture
def launcher(tmp_path):
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'android-runtime/scripts').mkdir(parents=True)
    (tmp_path / 'bin').mkdir()
    shutil.copy(LAUNCHER, tmp_path / 'scripts/start-console-android.sh')
    (tmp_path / '.env.console').touch()
    docker = tmp_path / 'bin/docker'
    docker.write_text(FAKE_DOCKER); docker.chmod(0o755)
    bench = tmp_path / 'android-runtime/scripts/start-bench.sh'
    bench.write_text('#!/bin/sh\nset -eu\ntouch "$FAKE_CREATED"\n'); bench.chmod(0o755)
    environment = dict(os.environ, PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}",
                       FAKE_DOCKER_LOG=str(tmp_path / 'docker.jsonl'), FAKE_CREATED=str(tmp_path / 'created'),
                       EMULYTIX_HOST_ID='user-other-host', EMULYTIX_BENCH_BOOT_TIMEOUT='1')
    for name in ('EMULYTIX_BENCH_CONTAINER', 'EMULYTIX_BENCH_NETWORK'):
        environment.pop(name, None)
    def run(**values):
        result = subprocess.run(['bash', str(tmp_path / 'scripts/start-console-android.sh')],
                                env={**environment, **values}, capture_output=True, text=True, timeout=10)
        calls = [json.loads(line) for line in (tmp_path / 'docker.jsonl').read_text().splitlines()]
        return result, calls
    return run, tmp_path


def test_existing_ready_bench_reuses_registration_and_forces_its_own_host(launcher):
    run, root = launcher
    for _ in range(2):
        result, calls = run(FAKE_DEVICE='true')
        assert result.returncode == 0, result.stderr
    assert not (root / 'created').exists()
    assert not [call for call in calls if call['event'] == 'registered']
    starts = [call for call in calls if 'up' in call.get('args', [])]
    assert len(starts) == 2
    assert all(call['host'] == 'bench-host' and call['adb'] == 'tcp:emulytix-wf01-android:5037' for call in starts)
    assert 'Aucun nouveau parcours' in result.stdout


def test_missing_bench_is_created_and_real_device_is_registered(launcher):
    run, root = launcher
    result, calls = run(FAKE_CONTAINER='false')
    assert result.returncode == 0, result.stderr
    assert (root / 'created').exists()
    registered = [call['fields'] for call in calls if call['event'] == 'registered']
    assert registered == [dict(device_id='local-emulator', display_name='Émulateur local',
                               host_id='bench-host', serial='emulator-5554', kind='emulator')]


def test_stopped_owned_bench_is_started_without_replacing_its_data(launcher):
    run, root = launcher
    result, calls = run(FAKE_RUNNING='false', FAKE_DEVICE='true')
    assert result.returncode == 0, result.stderr
    assert not (root / 'created').exists()
    assert any(call.get('args') == ['start', 'emulytix-wf01-android'] for call in calls)
    assert not any(call.get('args', [''])[0] in ('rm', 'create') for call in calls)


@pytest.mark.parametrize('failure', [
    {'FAKE_PERSISTENCE': ''},
    {'FAKE_COMMAND': 'legacy'},
    {'FAKE_COMMAND': 'guarded-force'},
    {'FAKE_COMMAND': 'wipe-data'},
    {'FAKE_COMMAND': 'unknown'},
    {'FAKE_COMMAND': 'wrong-shape'},
    {'FAKE_COMMAND': 'invalid-json'},
    {'FAKE_ENTRYPOINT': '["/custom-entrypoint"]'},
    {'FAKE_ENTRYPOINT': 'invalid-json'},
    {'FAKE_RUNNING': 'unknown'},
])
def test_legacy_or_unknown_stopped_bench_never_starts_or_mutates(launcher, failure):
    run, root = launcher
    result, calls = run(**{'FAKE_RUNNING': 'false', **failure})
    assert result.returncode != 0
    assert not (root / 'created').exists()
    assert not any(call.get('args', [''])[0] in ('start', 'rm', 'create') for call in calls)
    assert not any(call['event'] == 'registered' or 'up' in call.get('args', []) for call in calls)
    assert 'Aucun redémarrage' in result.stderr


def test_an_already_running_legacy_bench_is_not_restarted_or_blocked(launcher):
    run, root = launcher
    result, calls = run(FAKE_DEVICE='true', FAKE_PERSISTENCE='', FAKE_COMMAND='legacy')
    assert result.returncode == 0, result.stderr
    assert not any('.Config.Cmd' in ' '.join(call.get('args', [])) for call in calls)
    assert not any(call.get('args', [''])[0] in ('start', 'rm', 'create') for call in calls)


def test_new_bench_command_creates_the_avd_only_when_missing():
    source = LAUNCHER.parents[1] / 'android-runtime/scripts/start-bench.sh'
    command = source.read_text()
    assert 'if [[ ! -f "$ANDROID_AVD_HOME/emulytix-wf01.ini" ]]; then' in command
    assert 'avdmanager create avd --name emulytix-wf01' in command
    assert 'avdmanager create avd --force' not in command
    assert '--label emulytix.bench.persistence=preserve-avd-v1' in command


@pytest.mark.parametrize('failure', [{'FAKE_LABEL': 'foreign'}, {'FAKE_BOOT': '0'}, {'FAKE_BASE': 'false'}])
def test_invalid_runtime_never_registers_or_starts_worker(launcher, failure):
    run, _ = launcher
    result, calls = run(**failure)
    assert result.returncode != 0
    assert not [call for call in calls if call['event'] == 'registered' or 'up' in call.get('args', [])]
