"""Managed-emulator effects require an authoritative queued operation and device lease."""
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

from fastapi import HTTPException
import pytest

from app.emulator_store import EmulatorStore
from app.execution_store import ExecutionStore
from app.run_models import DeviceRegistration, RunSubmission, WorkflowRegistration
from app.telemetry import heartbeat
from test_authentication import auth_store
from test_user_roles import signed_in


@pytest.fixture
def store(database_dsn):
    heartbeat(database_dsn,'worker','worker-one','host-one',metrics={'managed_emulators':True})
    return EmulatorStore(database_dsn)


def create(store, *, apps=None, key='create-key', name='Paris Android'):
    return store.create_emulator(name,'host-one',apps if apps is not None else ['chrome'],key)[0]


def rows(store, table):
    assert table in {'devices','managed_emulators','runs','executions','workflows','emulator_operations'}
    with store.connect() as connection:
        return connection.execute('SELECT count(*) AS n FROM '+table).fetchone()['n']


def artifact(package='com.snapchat.android', **changes):
    identity = str(uuid4())
    return {'id':identity,'filename':identity+'.apk','sha256':'a'*64,'package_name':package,'name':'Local APK','size_bytes':10,**changes}


def ordinary_submission(device_id, **changes):
    return RunSubmission.model_validate({'workflow_id':'go-home','workflow_version':1,'device_ids':[device_id],
        'max_concurrency':1,'parameters':{},'idempotency_key':'ordinary',**changes})


def test_catalog_exposes_named_presets_without_fabricating_installed_or_available_apks(store):
    result = store.list_emulators()
    assert result['enabled'] and result['hosts']==['host-one'] and result['max_per_host']==4 and result['items']==[]
    catalog = {app['id']:app for app in result['applications']}
    assert set(catalog)=={'chrome','snapchat','linkedin','instagram','tiktok'}
    assert catalog['chrome']['available'] and catalog['chrome']['source']=='system'
    assert all(not catalog[key]['available'] and catalog[key]['size_bytes']==0 for key in catalog if key!='chrome')
    uploaded = store.add_application(artifact())
    catalog = store.list_emulators()['applications']
    snapchat = next(app for app in catalog if app['id']=='snapchat')
    assert snapchat['available'] and snapchat['size_bytes']==10
    assert not any(app['id']==uploaded['id'] for app in catalog)


def test_only_fresh_explicitly_capable_workers_are_advertised(store):
    with store.connect() as connection:
        connection.execute("UPDATE service_heartbeats SET last_seen_at=clock_timestamp()-interval '21 seconds'")
    heartbeat(store.dsn,'worker','ordinary','ordinary-host',metrics={})
    heartbeat(store.dsn,'worker','wrong-type','wrong-type-host',metrics={'managed_emulators':'true'})
    heartbeat(store.dsn,'worker','starting','starting-host',status='starting',metrics={'managed_emulators':True})
    assert store.list_emulators()['hosts']==[]
    assert store.list_emulators()['enabled'] is False
    with pytest.raises(HTTPException) as error:
        create(store)
    assert error.value.status_code==409 and rows(store,'devices')==0


def test_managed_emulator_returns_its_real_fleet_device_outside_the_first_inventory_page(store,control_client):
    with store.connect() as connection:
        with connection.cursor() as cursor:
            cursor.executemany('INSERT INTO devices(device_id,display_name,host_id,serial,kind) VALUES(%s,%s,%s,%s,%s)',
                [(f'a-{index:03d}',f'Inventory {index}','host-one',f'Serial{index}','physical') for index in range(100)])
    emulator = create(store)
    heartbeat(store.dsn,'worker','worker-one','host-one',metrics={'managed_emulators':True,'adb_status':'ready','devices':[{'serial':emulator['serial'],'state':'device'}]})
    page = control_client.get('/console/fleet?limit=100&offset=0').json()
    assert emulator['device_id'] not in {device['device_id'] for device in page['items']}
    device = control_client.get('/console/emulators').json()['items'][0]['device']
    assert device['device_id']==emulator['device_id'] and device['display_name']=='Paris Android'
    assert device['kind']=='emulator' and device['status']=='registered' and device['created_at']
    assert device['connection_status']=='connected' and device['worker_last_seen_at']
    assert device['active_run_id'] is None and device['lease_expires_at'] is None and device['availability']=='declared'
    with store.connect() as connection:
        connection.execute("UPDATE service_heartbeats SET last_seen_at=clock_timestamp()-interval '21 seconds'")
    assert store.list_emulators()['items'][0]['device']['connection_status']=='worker_offline'


def test_create_is_idempotent_and_reserves_one_slot_without_creating_runtime_jobs(store):
    first, created = store.create_emulator('  Friendly name  ','host-one',['chrome'],'request-one')
    assert created and first['device_id'].startswith('emu-') and first['state']=='created'
    assert first['installed_packages']==[] and first['serial']=='emulator-5556'
    again, created = store.create_emulator('  Friendly name  ','host-one',['chrome'],'request-one')
    assert not created and again['id']==first['id']
    with pytest.raises(HTTPException) as error:
        store.create_emulator('Different','host-one',['chrome'],'request-one')
    assert error.value.status_code==409
    assert rows(store,'devices')==rows(store,'managed_emulators')==1 and rows(store,'runs')==0


def test_concurrent_creation_replays_one_key_and_enforces_four_slots_without_orphans(store):
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _:create(store),range(6)))
    assert len({row['id'] for row in results})==1
    def reserve(index):
        try:
            return create(store,key='slot-'+str(index))
        except HTTPException as error:
            assert error.status_code==409
            return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(reserve,range(6)))
    assert len([row for row in results if row])==3
    assert rows(store,'devices')==rows(store,'managed_emulators')==4
    assert sorted(record['serial'] for record in store.list_managed('host-one'))==['emulator-5556','emulator-5558','emulator-5560','emulator-5562']


def test_creation_preserves_existing_unmanaged_device_ports(store):
    store.register_device(DeviceRegistration(device_id='already-present',host_id='host-one',serial='emulator-5556',kind='emulator'))
    assert create(store)['serial']=='emulator-5558'


def test_missing_preset_may_be_saved_but_cannot_be_started_or_prepared(store):
    emulator = create(store,apps=['chrome','snapchat'])
    assert emulator['application_ids']==['chrome','snapchat']
    for action in ['start','prepare']:
        with pytest.raises(HTTPException) as error:
            store.queue_operation(emulator['device_id'],action,action)
        assert error.value.status_code==422
    assert rows(store,'runs')==rows(store,'emulator_operations')==0
    assert store.queue_operation(emulator['device_id'],'stop','stop-missing')['run_id']


def test_trusted_operation_is_atomic_hidden_from_normal_catalog_and_pins_artifact_versions(store):
    old = artifact()
    store.add_application(old)
    emulator = create(store,apps=['snapchat'])
    queued = store.queue_operation(emulator['device_id'],'prepare','prepare-key')
    run = store.get_run(queued['run_id'])
    operation = store.operation(run['executions'][0]['id'])
    assert operation['id']==emulator['id'] and operation['authorized'] is True
    assert operation['applications'][0]['sha256']==old['sha256']
    store.add_application(artifact(sha256='b'*64))
    assert store.operation(run['executions'][0]['id'])['applications'][0]['sha256']==old['sha256']
    assert store.list_workflows(100,0)==[]
    assert [step['id'] for step in store.get_workflow(run['workflow_id'],1)['steps']]==['runtime','app-1']
    assert store.queue_operation(emulator['device_id'],'prepare','prepare-key')['run_id']==run['id']
    with pytest.raises(HTTPException) as error:
        store.queue_operation(emulator['device_id'],'stop','prepare-key')
    assert error.value.status_code==409 and rows(store,'runs')==1


def test_failure_between_run_creation_and_operation_marker_rolls_back_every_part(store,monkeypatch):
    emulator = create(store)
    original = store._submit_run
    def interrupted(connection,submission,**kwargs):
        original(connection,submission,**kwargs)
        raise RuntimeError('simulated interruption before trusted marker')
    monkeypatch.setattr(store,'_submit_run',interrupted)
    with pytest.raises(RuntimeError):
        store.queue_operation(emulator['device_id'],'start','interrupted')
    assert rows(store,'runs')==rows(store,'executions')==rows(store,'workflows')==rows(store,'emulator_operations')==0
    assert store.managed_device(emulator['device_id'])['last_run_id'] is None


def test_internal_workflows_cannot_be_registered_or_run_through_the_public_methods(store,workflow_payload):
    with pytest.raises(HTTPException) as error:
        store.register_workflow(WorkflowRegistration.model_validate({**workflow_payload,'workflow_id':'emulator-system-forged'}))
    assert error.value.status_code==403
    emulator = create(store)
    queued = store.queue_operation(emulator['device_id'],'start','start')
    run = store.get_run(queued['run_id'])
    with pytest.raises(HTTPException) as error:
        store.submit_run(ordinary_submission(emulator['device_id'],workflow_id=run['workflow_id'],idempotency_key='forged-run'))
    assert error.value.status_code==403 and rows(store,'runs')==1


def test_configuration_and_journeys_wait_for_preparation_and_all_queued_work(store,workflow_payload):
    emulator = create(store)
    device_id = emulator['device_id']
    store.register_workflow(WorkflowRegistration.model_validate(workflow_payload))
    with pytest.raises(HTTPException) as error:
        store.submit_run(ordinary_submission(device_id))
    assert error.value.status_code==409
    queued = store.queue_operation(device_id,'prepare','prepare')
    with pytest.raises(HTTPException) as error:
        store.configure(device_id,['chrome','instagram'])
    assert error.value.status_code==409
    with pytest.raises(HTTPException) as error:
        store.submit_run(ordinary_submission(device_id))
    assert error.value.status_code==409
    runtime = ExecutionStore(store.dsn)
    execution_id = store.get_run(queued['run_id'])['executions'][0]['id']
    grant = runtime.claim(execution_id,'worker',30)
    assert store.update_runtime(device_id,'ready',['com.android.chrome'],execution_id=execution_id,owner_id='worker',lease_epoch=grant['lease_epoch'])
    assert runtime.finish(execution_id,'worker',grant['lease_epoch'],'succeeded')
    normal = store.submit_run(ordinary_submission(device_id,parameters={'emulator_operation':{'action':'stop'}}))
    assert store.operation(normal['executions'][0]['id']) is None
    for action in ['stop','prepare']:
        with pytest.raises(HTTPException) as error:
            store.queue_operation(device_id,action,action+'-busy')
        assert error.value.status_code==409


def test_normal_run_and_stop_cannot_both_slip_through_concurrent_admission(store,workflow_payload):
    emulator = create(store)
    device_id = emulator['device_id']
    store.register_workflow(WorkflowRegistration.model_validate(workflow_payload))
    with store.connect() as connection:
        connection.execute("UPDATE managed_emulators SET state='ready' WHERE device_id=%s",(device_id,))
    def submit(kind):
        try:
            return store.submit_run(ordinary_submission(device_id)) if kind=='journey' else store.queue_operation(device_id,'stop','stop-race')
        except HTTPException as error:
            assert error.status_code==409
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit,['journey','stop']))
    assert sum(row is not None for row in results)==1 and rows(store,'runs')==1


def test_runtime_updates_are_fenced_and_terminal_errors_are_visible(store):
    emulator = create(store)
    device_id = emulator['device_id']
    queued = store.queue_operation(device_id,'prepare','prepare')
    execution_id = store.get_run(queued['run_id'])['executions'][0]['id']
    assert not store.update_runtime(device_id,'ready',execution_id=execution_id,owner_id='worker',lease_epoch=1)
    runtime = ExecutionStore(store.dsn)
    grant = runtime.claim(execution_id,'worker',30)
    assert not store.update_runtime(device_id,'ready',execution_id=execution_id,owner_id='other',lease_epoch=grant['lease_epoch'])
    assert not store.update_runtime(device_id,'ready',execution_id=execution_id,owner_id='worker',lease_epoch=grant['lease_epoch']+1)
    assert runtime.finish(execution_id,'worker',grant['lease_epoch'],'failed',error='APK installation failed')
    assert not store.update_runtime(device_id,'ready',execution_id=execution_id,owner_id='worker',lease_epoch=grant['lease_epoch'])
    record = store.managed_device(device_id)
    assert record['state']=='failed' and record['last_error']=='APK installation failed'


def test_changed_configuration_invalidates_readiness_without_claiming_a_running_emulator_is_uncreated(store,workflow_payload):
    emulator = create(store)
    device_id = emulator['device_id']
    with store.connect() as connection:
        connection.execute("UPDATE managed_emulators SET state='ready' WHERE device_id=%s",(device_id,))
    assert store.configure(device_id,['chrome','instagram'])['state']=='unknown'
    store.register_workflow(WorkflowRegistration.model_validate(workflow_payload))
    with pytest.raises(HTTPException) as error:
        store.submit_run(ordinary_submission(device_id))
    assert error.value.status_code==409


def test_failed_lifecycle_operation_blocks_journeys_even_if_previous_runtime_state_was_ready(store,workflow_payload):
    emulator = create(store)
    device_id = emulator['device_id']
    with store.connect() as connection:
        connection.execute("UPDATE managed_emulators SET state='ready' WHERE device_id=%s",(device_id,))
    queued = store.queue_operation(device_id,'stop','stop-failed')
    runtime = ExecutionStore(store.dsn)
    execution_id = store.get_run(queued['run_id'])['executions'][0]['id']
    grant = runtime.claim(execution_id,'worker',30)
    assert runtime.finish(execution_id,'worker',grant['lease_epoch'],'failed',error='Stop failed')
    store.register_workflow(WorkflowRegistration.model_validate(workflow_payload))
    with pytest.raises(HTTPException) as error:
        store.submit_run(ordinary_submission(device_id))
    assert error.value.status_code==409


@pytest.mark.parametrize('role',['admin','operator','builder','viewer','auditor'])
def test_managed_routes_enforce_device_permissions_and_replay_creation(auth_store,app_module,role):
    heartbeat(auth_store.config.dsn,'worker','managed','host-one',metrics={'managed_emulators':True})
    user, client, _ = signed_in(auth_store,app_module,role)
    assert client.get('/console/emulators').status_code==200
    payload = {'name':'  Téléphone de Paris  ','host_id':'host-one','application_ids':['chrome'],'idempotency_key':'same-client-key'}
    response = client.post('/console/emulators',json=payload)
    if role not in {'admin','operator'}:
        assert response.status_code==403
        return
    assert response.status_code==201,response.text
    record = response.json()
    assert record['display_name']=='Téléphone de Paris'
    assert client.post('/console/emulators',json=payload).status_code==200
    for spoof in [{'image':'untrusted'},{'container_name':'foreign'},{'serial':'emulator-5554'}]:
        assert client.post('/console/emulators',json={**payload,**spoof}).status_code==422
    assert client.post(f"/console/emulators/{record['device_id']}/configuration",json={'application_ids':['chrome','tiktok']}).status_code==200
    assert client.post(f"/console/emulators/{record['device_id']}/prepare",json={'idempotency_key':'missing-apk'}).status_code==422
    result = client.post(f"/console/emulators/{record['device_id']}/stop",json={'idempotency_key':'stop'})
    assert result.status_code==202,result.text
    operation_store = EmulatorStore(auth_store.config.dsn)
    execution_id = operation_store.get_run(UUID(result.json()['run_id']))['executions'][0]['id']
    assert operation_store.operation(execution_id)['authorized']
    with auth_store.connect() as connection:
        connection.execute("UPDATE auth_users SET role='viewer' WHERE id=%s",(user['id'],))
    assert operation_store.operation(execution_id)['authorized'] is False
    with auth_store.connect() as connection:
        connection.execute('DELETE FROM auth_users WHERE id=%s',(user['id'],))
    assert operation_store.operation(execution_id)['authorized'] is False


def test_upload_uses_inspected_metadata_and_updates_the_matching_preset(auth_store,app_module,monkeypatch):
    _, client, _ = signed_in(auth_store,app_module,'admin')
    metadata = artifact()
    async def inspected(file,name=None):
        assert file.filename=='snapchat.apk'
        return metadata
    monkeypatch.setattr('app.apk_catalog.ingest_apk',inspected)
    result = client.post('/console/applications',files={'file':('snapchat.apk',b'validated by fake inspector','application/vnd.android.package-archive')})
    assert result.status_code==201,result.text
    catalog = client.get('/console/emulators').json()['applications']
    assert next(app for app in catalog if app['id']=='snapchat')['available']
