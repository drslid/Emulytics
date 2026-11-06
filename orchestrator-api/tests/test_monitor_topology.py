"""Topology activity comes from bounded persisted evidence, never invented HTTP traffic."""
from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from app.execution_store import ExecutionStore
from app.monitor_topology import topology_snapshot
from app.run_models import RunSubmission
from app.telemetry import heartbeat


@pytest.fixture
def topology_case(registered,database_dsn,run_payload,tmp_path,monkeypatch):
    monkeypatch.setenv('EMULYTIX_ARTIFACT_ROOT',str(tmp_path))
    store = ExecutionStore(database_dsn)
    run = store.submit_run(RunSubmission.model_validate(run_payload))
    return store,run,datetime.now(timezone.utc)


def observe(case,services=None):
    store,_,observed = case
    with store.connect() as connection:
        return topology_snapshot(connection,observed,services or [])


def test_empty_topology_is_idle_without_fabricated_network_traffic(topology_case):
    result = observe(topology_case)
    assert result['window_seconds']==15
    assert set(result['events'])=={'console_commands','scheduled_runs','executions_started','actions_completed','steps_published','captures_published'}
    assert all(event=={'count':0,'last_at':None} for event in result['events'].values())
    assert result['storage']=={'status':'readable'}
    assert result['sampling']=={'limit':1000,'events_truncated':False,'captures_truncated':False}
    assert result['confirmed_device_executions']==0
    assert result['confirmed_device_executions_valid_for_seconds'] is None
    assert 'http_requests' not in result


def actor(connection):
    identity = uuid4()
    connection.execute(
        "INSERT INTO auth_users(id,username,password_hash,display_name) VALUES(%s,'topology-actor','unused','Fixture')",
        (identity,),
    )
    return identity


def test_console_commands_require_authenticated_successful_business_mutations(topology_case):
    store,run,observed = topology_case
    paths = ['/runs',f'/runs/{run["id"]}/cancel','/devices','/console/emulators',
             '/console/emulators/phone-1/start','/console/applications','/console/schedules']
    with store.connect() as connection:
        identity = actor(connection)
        rows = [(observed,identity,'http.mutation',path,'access',Jsonb({'status_code':201})) for path in paths]
        for code in (199,300,307,400,403,500,'201',None,True,{},201.5):
            rows.append((observed,identity,'http.mutation','/runs','access',Jsonb({'status_code':code})))
        for path in ('/auth/login','/console/account','/console/account/password','/console/auth/verify',
                     '/workflows','/runs/not-a-uuid/cancel','/devices/phone-1/screen','/console'):
            rows.append((observed,identity,'http.mutation',path,'access',Jsonb({'status_code':200})))
        rows.extend([
            (observed,None,'http.mutation','/runs','access',Jsonb({'status_code':202})),
            (observed,identity,'http.rejected','/runs','access',Jsonb({'status_code':202})),
            (observed,identity,'http.mutation','/runs','security',Jsonb({'status_code':202})),
            (observed+timedelta(microseconds=1),identity,'http.mutation','/runs','access',Jsonb({'status_code':202})),
            (observed-timedelta(seconds=15,microseconds=1),identity,'http.mutation','/runs','access',Jsonb({'status_code':202})),
        ])
        with connection.cursor() as cursor:
            cursor.executemany('INSERT INTO audit_log(occurred_at,actor_id,action,entity_id,category,metadata) '
                               'VALUES(%s,%s,%s,%s,%s,%s)',rows)
    assert observe(topology_case)['events']['console_commands']=={'count':len(paths),'last_at':observed}


def test_activity_uses_closed_fifteen_second_window_and_only_allowlisted_types(topology_case):
    store,run,observed = topology_case
    start = observed-timedelta(seconds=15)
    with store.connect() as connection:
        for sequence,(kind,when) in enumerate((
            ('execution.started',start),('action.done',observed),('execution.step_completed',observed-timedelta(seconds=3)),
            ('action.done',start-timedelta(microseconds=1)),('execution.started',observed+timedelta(microseconds=1)),
            ('action.intent',observed),('execution.failed',observed)),2):
            connection.execute('INSERT INTO run_events(run_id,sequence,type,payload,created_at) VALUES(%s,%s,%s,%s,%s)',
                               (run['id'],sequence,kind,Jsonb({'secret':'NEVER-PUBLISH-THIS-PAYLOAD'}),when))
        connection.execute("INSERT INTO audit_log(action,category,occurred_at) VALUES('schedule.dispatched','automation',%s),"
                           "('schedule.dispatched','security',%s),('schedule.failed','automation',%s),"
                           "('schedule.dispatched','automation',%s)",
                           (start,observed,observed,observed+timedelta(microseconds=1)))
    result = observe(topology_case)
    assert result['events']['executions_started']=={'count':1,'last_at':start}
    assert result['events']['actions_completed']=={'count':1,'last_at':observed}
    assert result['events']['steps_published']=={'count':1,'last_at':observed-timedelta(seconds=3)}
    assert result['events']['scheduled_runs']=={'count':1,'last_at':start}
    assert 'NEVER-PUBLISH-THIS-PAYLOAD' not in json.dumps(result,default=str)


def test_audit_and_run_events_share_one_declared_sample_cap(topology_case):
    store,run,observed = topology_case
    with store.connect() as connection:
        connection.execute("INSERT INTO audit_log(action,category,occurred_at) "
                           "SELECT 'schedule.dispatched','automation',%s FROM generate_series(1,501)",(observed,))
        connection.execute("INSERT INTO run_events(run_id,sequence,type,payload,created_at) "
                           "SELECT %s,n+1,'action.done','{}',%s FROM generate_series(1,501) n",(run['id'],observed))
    result = observe(topology_case)
    assert sum(value['count'] for value in result['events'].values())==1000
    assert result['sampling']=={'limit':1000,'events_truncated':True,'captures_truncated':False}


def screenshot(captured_at, name='a'*32):
    return {'screenshot':f'/private/execution/{name}.png','screenshot_sha256':'b'*64,
            'captured_at':captured_at.isoformat() if isinstance(captured_at,datetime) else captured_at}


def test_captures_count_valid_published_metadata_without_reading_files(topology_case):
    store,run,observed = topology_case
    captured = observed-timedelta(seconds=2)
    valid = screenshot(captured)
    steps = [valid,valid,screenshot('invalid'),screenshot('2026-11-06T14:01:00'),
             screenshot(observed+timedelta(microseconds=1)),screenshot(observed-timedelta(seconds=16)),
             {**valid,'screenshot_sha256':'not-a-digest'},{**valid,'screenshot':'/private/other.jpg'},
             None,{'captured_at':captured.isoformat()},screenshot(observed.astimezone(timezone(timedelta(hours=5,minutes=30))),'c'*32)]
    with store.connect() as connection:
        connection.execute('UPDATE executions SET updated_at=%s,evidence=%s WHERE run_id=%s',
                           (observed,Jsonb({'steps':steps}),run['id']))
    result = observe(topology_case)
    assert result['events']['captures_published']=={'count':2,'last_at':observed}
    assert result['sampling']['captures_truncated'] is False
    assert '/private/' not in json.dumps(result,default=str)


def test_capture_scanning_is_bounded_by_executions_and_reports_truncation(topology_case):
    store,run,observed = topology_case
    with store.connect() as connection:
        connection.execute("INSERT INTO executions(id,run_id,device_id,attempt,updated_at,evidence) "
                           "SELECT gen_random_uuid(),%s,'phone-1',n+1,%s,%s FROM generate_series(1,1001) n",
                           (run['id'],observed,Jsonb({'steps':[screenshot(observed)]})))
    result = observe(topology_case)
    assert result['events']['captures_published']=={'count':1000,'last_at':observed}
    assert result['sampling']['captures_truncated'] is True


def test_capture_scanning_caps_steps_and_rejects_malformed_evidence(topology_case):
    store,run,observed = topology_case
    with store.connect() as connection:
        connection.execute('UPDATE executions SET updated_at=%s,evidence=%s WHERE run_id=%s',
                           (observed,Jsonb({'steps':[screenshot(observed,f'{n:032x}') for n in range(15)]}),run['id']))
    result = observe(topology_case)
    assert result['events']['captures_published']['count']==14
    assert result['sampling']['captures_truncated'] is True
    for evidence in ([],None,{'steps':{}},{'steps':[{'captured_at':{}},'untrusted']}):
        with store.connect() as connection:
            connection.execute('UPDATE executions SET evidence=%s WHERE run_id=%s',(Jsonb(evidence),run['id']))
        result = observe(topology_case)
        assert result['events']['captures_published']=={'count':0,'last_at':None}


def test_capture_candidates_exclude_updates_outside_snapshot_window(topology_case):
    store,run,observed = topology_case
    for updated_at in (observed-timedelta(seconds=16),observed+timedelta(microseconds=1)):
        with store.connect() as connection:
            connection.execute('UPDATE executions SET updated_at=%s,evidence=%s WHERE run_id=%s',
                               (updated_at,Jsonb({'steps':[screenshot(observed)]}),run['id']))
        assert observe(topology_case)['events']['captures_published']=={'count':0,'last_at':None}


def test_storage_reports_only_directory_readability(topology_case,tmp_path,monkeypatch):
    monkeypatch.delenv('EMULYTIX_ARTIFACT_ROOT')
    assert observe(topology_case)['storage']=={'status':'unconfigured'}
    monkeypatch.setenv('EMULYTIX_ARTIFACT_ROOT',str(tmp_path/'absent'))
    assert observe(topology_case)['storage']=={'status':'unavailable'}
    file = tmp_path/'regular-file'
    file.write_text('not a directory')
    monkeypatch.setenv('EMULYTIX_ARTIFACT_ROOT',str(file))
    assert observe(topology_case)['storage']=={'status':'unavailable'}
    monkeypatch.setenv('EMULYTIX_ARTIFACT_ROOT',str(tmp_path))
    assert observe(topology_case)['storage']=={'status':'readable'}


@pytest.fixture
def owned_topology(topology_case,database_dsn):
    store,run,observed = topology_case
    execution = run['executions'][0]['id']
    assert store.claim(execution,'worker-owner',60,host_id='host-1')
    heartbeat(database_dsn,'worker','worker-owner','host-1',metrics={
        'adb_status':'ready','devices':[{'serial':'emulator-5554','state':'device'}]})
    with store.connect() as connection:
        connection.execute('UPDATE executions SET started_at=%s WHERE id=%s',(observed-timedelta(seconds=1),execution))
        connection.execute('UPDATE service_heartbeats SET last_seen_at=%s',(observed-timedelta(seconds=1),))
    return topology_case


def owner_services(case):
    store,_,observed = case
    with store.connect() as connection:
        return connection.execute("SELECT *,last_seen_at>%s-interval '20 seconds' AS live FROM service_heartbeats",
                                  (observed,)).fetchall()


def test_confirmed_device_execution_requires_live_exact_owner_and_adb_observation(owned_topology):
    services = owner_services(owned_topology)
    result = observe(owned_topology,services)
    assert result['confirmed_device_executions']==1
    assert result['confirmed_device_executions_valid_for_seconds']==pytest.approx(19)
    # Another connected worker cannot stand in for the owner that lacks ADB proof.
    owner = {**services[0],'metrics':{'adb_status':'unavailable'}}
    other = {**services[0],'instance_id':'other-connected-worker'}
    assert observe(owned_topology,[owner,other])['confirmed_device_executions']==0


def test_confirmed_device_proof_expires_with_shortest_remaining_lease(owned_topology):
    store,_,observed = owned_topology
    with store.connect() as connection:
        connection.execute('UPDATE device_leases SET expires_at=%s',(observed+timedelta(seconds=1.25),))
    result = observe(owned_topology,owner_services(owned_topology))
    assert result['confirmed_device_executions']==1
    assert result['confirmed_device_executions_valid_for_seconds']==pytest.approx(1.25)


def test_another_fresh_owner_cannot_extend_expiring_execution_proof(owned_topology,database_dsn):
    store,run,observed = owned_topology
    second = uuid4()
    heartbeat(database_dsn,'worker','second-owner','host-2',metrics={
        'adb_status':'ready','devices':[{'serial':'PhysicalCaseSensitive','state':'device'}]})
    with store.connect() as connection:
        connection.execute("UPDATE service_heartbeats SET last_seen_at=%s WHERE instance_id='worker-owner'",
                           (observed-timedelta(seconds=19),))
        connection.execute("UPDATE service_heartbeats SET last_seen_at=%s WHERE instance_id='second-owner'",
                           (observed-timedelta(seconds=1),))
        connection.execute("INSERT INTO devices(device_id,host_id,serial,kind) "
                           "VALUES('phone-2','host-2','PhysicalCaseSensitive','physical')")
        connection.execute("INSERT INTO executions(id,run_id,device_id,status,lease_epoch,started_at) "
                           "VALUES(%s,%s,'phone-2','running',3,%s)",(second,run['id'],observed-timedelta(seconds=1)))
        connection.execute("INSERT INTO device_leases(device_id,execution_id,owner_id,lease_epoch,expires_at) "
                           "VALUES('phone-2',%s,'second-owner',3,%s)",(second,observed+timedelta(seconds=50)))
    result = observe(owned_topology,owner_services(owned_topology))
    assert result['confirmed_device_executions']==2
    assert result['confirmed_device_executions_valid_for_seconds']==pytest.approx(1)


@pytest.mark.parametrize('change',[
    "UPDATE device_leases SET expires_at='2000-01-01'",
    'UPDATE device_leases SET quarantined=true',
    'UPDATE device_leases SET lease_epoch=lease_epoch+1',
    "UPDATE device_leases SET owner_id='different-owner'",
    "UPDATE executions SET status='succeeded'",
    'UPDATE executions SET started_at=NULL',
    "UPDATE executions SET started_at='2100-01-01'",
    "UPDATE service_heartbeats SET host_id='different-host'",
    "UPDATE service_heartbeats SET status='unavailable'",
    "UPDATE service_heartbeats SET last_seen_at='2000-01-01'",
    "UPDATE service_heartbeats SET last_seen_at='2100-01-01'",
    "UPDATE service_heartbeats SET metrics='{}'",
    "UPDATE service_heartbeats SET metrics='{\"adb_status\":\"ready\",\"devices\":[{\"serial\":\"Emulator-5554\",\"state\":\"device\"}]}'",
])
def test_unconfirmed_lease_or_owner_never_animates_as_connected_execution(owned_topology,change):
    store,_,_ = owned_topology
    with store.connect() as connection:
        connection.execute(change)
    result = observe(owned_topology,owner_services(owned_topology))
    assert result['confirmed_device_executions']==0
    assert result['confirmed_device_executions_valid_for_seconds'] is None


@pytest.mark.parametrize('window',['1h','24h','7d'])
def test_monitor_routes_publish_topology_with_independent_activity_window(control_client,window):
    response = control_client.get('/console/monitor',params={'window':window})
    assert response.status_code==200,response.text
    data = response.json()
    assert data['results']['window']==window
    assert data['topology']['window_seconds']==15
    assert all(event=={'count':0,'last_at':None} for event in data['topology']['events'].values())
