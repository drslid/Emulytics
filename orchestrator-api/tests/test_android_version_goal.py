"""Settings/version goals must return observed device facts, never a generated guess."""
import json
from pathlib import Path
import sys
from uuid import uuid4

import pytest

from app.android_driver import AndroidDriver, DriverError
from app.journey_generation import local_goal
from app.run_models import DeviceRegistration, RunSubmission, WorkflowRegistration
from app.run_store import RunStore
from app.worker import Worker
from test_authentication import auth_store
from test_user_roles import signed_in


USER_GOAL = "ouvre les parametres du telephone et donne moi la version d'android"
PACKAGE_ASSERTION = {'type': 'package', 'value': 'com.android.settings'}


def settings_step(section='about', **extra):
    return {'id': 'open-phone-settings', 'action': 'open_settings',
            'args': {'section': section, **extra}, 'assert': PACKAGE_ASSERTION, 'timeout_ms': 10_000}


def version_step(**args):
    return {'id': 'read-android-version', 'action': 'read_device_info',
            'args': {'field': 'android_version', **args}, 'assert': PACKAGE_ASSERTION, 'timeout_ms': 10_000}


@pytest.mark.parametrize('goal', [
    USER_GOAL,
    'Ouvre les paramètres du téléphone et donne-moi la version d’Android.',
])
def test_complete_settings_goal_compiles_without_a_model(goal):
    result = local_goal(goal)
    assert result is not None
    recipe = result['recipe']
    assert recipe['instructions'] == goal
    assert recipe['steps'][0]['action'] == 'open_settings'
    assert recipe['steps'][0]['args'] == {'section': 'main'}
    reads = [step for step in recipe['steps'] if step['action'] == 'read_device_info']
    assert len(reads) == 1 and reads[0]['args'] == {'field': 'android_version'}
    for step in recipe['steps']:
        AndroidDriver.validate_step(step)
    assert 'result' not in reads[0], 'No observed version exists before the run'


@pytest.mark.parametrize('goal', [
    USER_GOAL + ' et réinitialise le téléphone',
    USER_GOAL + ', puis envoie un message à Alice',
    'Supprime mes fichiers puis ' + USER_GOAL,
    USER_GOAL + ' et active le débogage USB',
])
def test_settings_goal_does_not_drop_an_additional_action(goal):
    assert local_goal(goal) is None


@pytest.mark.parametrize('step', [
    settings_step('factory_reset'),
    settings_step('android.settings.WIFI_SETTINGS'),
    settings_step(intent='android.settings.SETTINGS'),
    settings_step(package_name='attacker.package'),
    settings_step(None),
    settings_step([]),
    dict(settings_step(), args={}),
    version_step(field='ro.serialno'),
    version_step(field=[]),
    dict(version_step(), args={}),
    version_step(property='ro.build.version.release'),
    version_step(command='id'),
])
def test_new_actions_reject_arbitrary_properties_intents_and_commands(step, tmp_path, version_adb):
    with pytest.raises(DriverError):
        AndroidDriver.validate_step(step)
    with pytest.raises(DriverError):
        observer(tmp_path, version_adb).execute_step(step)
    assert not version_adb[1].exists(), 'Invalid arguments must fail before contacting ADB'


@pytest.fixture
def version_adb(tmp_path, monkeypatch):
    executable, log = tmp_path / 'adb', tmp_path / 'commands.jsonl'
    executable.write_text(
        f'#!{sys.executable}\n'
        'import json,os,sys\n'
        "args=sys.argv[1:]\n"
        "with open(os.environ['VERSION_ADB_LOG'],'a') as out: out.write(json.dumps(args)+'\\n')\n"
        "args=args[args.index('-s')+2:]\n"
        "if args==['shell','getprop','ro.build.version.release']: print(os.environ.get('VERSION_RELEASE','15'))\n"
        "elif args==['shell','getprop','ro.build.version.sdk']: print(os.environ.get('VERSION_SDK','35'))\n"
        "elif args==['shell','dumpsys','window']: print('mCurrentFocus=Window{a u0 com.android.settings/.Settings}')\n"
        "elif args[:3]==['shell','uiautomator','dump']: print(os.environ.get('VERSION_DUMP_OUTPUT','UI hierarchy dumped to: '+args[-1]))\n"
        "elif args[:2]==['shell','cat']: print('<hierarchy><node package=\"com.android.settings\" text=\"Android version\" /></hierarchy>')\n"
        "elif args[:2]==['exec-out','screencap']:\n"
        " sys.stdout.buffer.write(b'not PNG' if os.environ.get('VERSION_BAD_PNG') else b'\\x89PNG\\r\\n\\x1a\\nDATA')\n"
        "else: print('OK')\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv('VERSION_ADB_LOG', str(log))
    return executable, log


def observer(tmp_path, version_adb):
    return AndroidDriver('emulator-5554', lambda *_: None, lambda: None,
                         tmp_path / 'artifacts', adb_binary=str(version_adb[0]))


def logged_commands(version_adb):
    return [json.loads(line) for line in version_adb[1].read_text().splitlines()]


@pytest.mark.parametrize('section,intent', [('about', 'android.settings.DEVICE_INFO_SETTINGS'),
                                          ('main', 'android.settings.SETTINGS')])
def test_open_settings_uses_only_a_fixed_intent_and_keeps_existing_proofs(tmp_path, version_adb, section, intent):
    evidence = observer(tmp_path, version_adb).execute_step(settings_step(section))
    calls = logged_commands(version_adb)
    assert all(call[:2] == ['-s', 'emulator-5554'] for call in calls)
    intents = [call for call in calls if intent in call]
    assert len(intents) == 1
    assert intents[0][2:5] == ['shell', 'am', 'start']
    assert intents[0][-2:] == ['-p', 'com.android.settings']
    assert evidence['assertion_passed'] is True
    assert Path(evidence['screenshot']).is_file()
    assert Path(evidence['ui_xml']).is_file()


def test_android_version_result_comes_from_fixed_properties(tmp_path, version_adb):
    evidence = observer(tmp_path, version_adb).execute_step(version_step())
    assert evidence['result'] == {'type': 'android_version', 'value': '15', 'sdk_int': 35,
                                  'source': 'android_system_properties'}
    props = [call[4:] for call in logged_commands(version_adb) if call[2:4] == ['shell', 'getprop']]
    assert props == [['ro.build.version.release'], ['ro.build.version.sdk']]
    assert evidence['assertion_passed'] is True and Path(evidence['screenshot']).is_file()


@pytest.mark.parametrize('release,sdk', [('', '35'), ('15', ''), ('15', 'not-an-integer'),
                                        ('15\n16', '35'), ('15', '0'), ('15', '10001'),
                                        ('15', '٣٥'), ('x' * 65, '35'), ('\t15', '35'),
                                        ('15\x0b', '35'), ('unknown', '35'), ('15', '\t35')])
def test_invalid_system_observation_is_not_a_successful_result(tmp_path, version_adb, monkeypatch, release, sdk):
    monkeypatch.setenv('VERSION_RELEASE', release)
    monkeypatch.setenv('VERSION_SDK', sdk)
    with pytest.raises(DriverError):
        observer(tmp_path, version_adb).execute_step(version_step())
    assert not (tmp_path / 'artifacts').exists()


@pytest.mark.parametrize('release', ['Android Éclair Beta', '  Android X  '])
def test_release_is_an_observed_opaque_label_not_a_numeric_guess(tmp_path, version_adb, monkeypatch, release):
    monkeypatch.setenv('VERSION_RELEASE', release)
    evidence = observer(tmp_path, version_adb).execute_step(version_step())
    assert evidence['result']['value'] == release.strip()
    assert evidence['result']['sdk_int'] == 35


def test_a_valid_version_without_a_valid_screenshot_is_not_success(tmp_path, version_adb, monkeypatch):
    monkeypatch.setenv('VERSION_BAD_PNG', '1')
    with pytest.raises(DriverError):
        observer(tmp_path, version_adb).execute_step(version_step())


@pytest.mark.parametrize('dump_output', ['ERROR: could not get idle state.',
                                       'UI hierarchy dumped to: /sdcard/stale-ui.xml'])
def test_failed_or_wrong_target_dump_cannot_reuse_stale_xml_as_version_proof(
        tmp_path, version_adb, monkeypatch, dump_output):
    monkeypatch.setenv('VERSION_DUMP_OUTPUT', dump_output)
    with pytest.raises(DriverError):
        observer(tmp_path, version_adb).execute_step(version_step())
    calls = logged_commands(version_adb)
    assert any(call[2:5] == ['shell', 'uiautomator', 'dump'] for call in calls)
    assert not any(call[2:4] == ['shell', 'cat'] for call in calls)
    assert not list((tmp_path / 'artifacts').glob('*.xml'))


def test_skipped_read_does_not_invent_a_result_or_read_properties(tmp_path, version_adb):
    step = version_step()
    step['when'] = {'type': 'ui', 'selector': {'text': 'Not present'}}
    evidence = observer(tmp_path, version_adb).execute_step(step)
    assert evidence['skipped'] is True and 'result' not in evidence
    assert not any(call[2:4] == ['shell', 'getprop'] for call in logged_commands(version_adb))


@pytest.mark.parametrize('role', ['admin', 'builder', 'operator', 'viewer', 'auditor'])
def test_settings_generation_respects_roles_without_creating_or_executing(auth_store, app_module, monkeypatch, role):
    from app.journey_provider import JourneyProvider

    monkeypatch.setattr(JourneyProvider, 'generate', lambda *_: pytest.fail('Recognized device-info goal must be local'))
    _, client, _ = signed_in(auth_store, app_module, role)
    tables = ('automation_recipes', 'workflows', 'runs', 'executions', 'chatgpt_connections')
    with auth_store.connect() as connection:
        before = {table: connection.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n'] for table in tables}
    response = client.post('/console/recipes/generate', json={'instructions': USER_GOAL})
    assert response.status_code == (200 if role in ('admin', 'builder') else 403), response.text
    if response.status_code == 200:
        steps = response.json()['recipe']['steps']
        assert any(step['action'] == 'read_device_info' for step in steps)
    with auth_store.connect() as connection:
        after = {table: connection.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n'] for table in tables}
    assert after == before


@pytest.mark.parametrize('steps,expected_status', [
    ([settings_step(), version_step()], 200),
    ([settings_step(intent='android.settings.WIFI_SETTINGS'), version_step()], 422),
    ([settings_step(), version_step(field='ro.serialno')], 422),
    ([settings_step(), version_step(command='id')], 422),
    ([settings_step()], 422),
])
def test_model_generated_settings_actions_are_bounded_before_returning_a_draft(
        auth_store, app_module, monkeypatch, steps, expected_status):
    from app.journey_provider import JourneyProvider

    goal = 'Depuis les réglages système, relève la version Android du mobile.'
    assert local_goal(goal) is None
    calls = []

    def generated(_provider, _session, instructions):
        calls.append(instructions)
        return {'supported': True, 'name': 'Android version',
                'reason': 'The version will be observed during execution.', 'steps_json': json.dumps(steps)}

    monkeypatch.setattr(JourneyProvider, 'generate', generated)
    _, client, _ = signed_in(auth_store, app_module, 'builder')
    response = client.post('/console/recipes/generate', json={'instructions': goal})
    assert response.status_code == expected_status, response.text
    assert calls == [goal]
    if expected_status == 200:
        result = response.json()
        assert result['source'] == 'chatgpt' and result['requires_test'] is True
        assert result['recipe']['steps'][-1]['action'] == 'read_device_info'
        assert result['recipe']['steps'][-1]['args'] == {'field': 'android_version'}
    with auth_store.connect() as connection:
        for table in ('automation_recipes', 'workflows', 'runs', 'executions'):
            assert connection.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n'] == 0


def test_worker_persists_the_observed_android_version_with_its_capture(database_dsn, tmp_path, version_adb):
    goal = local_goal(USER_GOAL)
    assert goal is not None
    store = RunStore(database_dsn)
    store.register_device(DeviceRegistration(device_id='settings-phone', host_id='version-host',
                                             serial='emulator-5554', kind='physical'))
    store.register_workflow(WorkflowRegistration(workflow_id='android-version', version=1,
                                                 steps=goal['recipe']['steps']))
    run = store.submit_run(RunSubmission(workflow_id='android-version', workflow_version=1,
                                         device_ids=['settings-phone'], max_concurrency=1,
                                         idempotency_key=str(uuid4())))

    def driver_factory(serial, before_command, poll, artifact_dir, **kwargs):
        return AndroidDriver(serial, before_command, poll, artifact_dir,
                             adb_binary=str(version_adb[0]), **kwargs)

    worker = Worker(database_dsn, 'version-host', lock_root=tmp_path / 'locks',
                    artifact_root=tmp_path / 'worker-artifacts', driver_factory=driver_factory)
    assert worker.run_once()
    saved = store.get_run(run['id'])
    assert saved['status'] == 'succeeded'
    observed = [step for step in saved['executions'][0]['evidence']['steps'] if 'result' in step]
    assert len(observed) == 1
    assert observed[0]['result']['value'] == '15' and observed[0]['result']['sdk_int'] == 35
    assert Path(observed[0]['screenshot']).is_file()
    assert observed[0]['assertion_passed'] is True
