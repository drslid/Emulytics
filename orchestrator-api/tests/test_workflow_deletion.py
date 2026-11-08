"""Removing a published version prevents new work without erasing its history."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb
import pytest

from app.automation_models import RecipeInput, ScheduleInput
from app.automation_store import AutomationStore
from app.run_models import DeviceRegistration, RunSubmission, WorkflowRegistration
from app.run_recovery import RecoveryStore, RetryInput
from app.run_store import RunStore
from test_authentication import auth_store
from test_user_roles import signed_in


@pytest.fixture
def published(database_dsn, workflow_payload):
    store = AutomationStore(database_dsn)
    store.register_device(DeviceRegistration(device_id='delete-phone', host_id='test-host', serial='DeleteSerial', kind='physical'))
    saved = store.create_recipe(RecipeInput(name='Disposable publication', instructions='Go home', steps=workflow_payload['steps']), None)
    return store, store.publish_recipe(saved['id'], saved['revision'], None)


def submission(recipe, key=None):
    return RunSubmission(workflow_id=recipe['workflow_id'], workflow_version=1,
                         device_ids=['delete-phone'], max_concurrency=1, idempotency_key=key or str(uuid4()))


def finish(store, run, status='succeeded'):
    with store.connect() as connection:
        connection.execute('UPDATE runs SET status=%s WHERE id=%s', (status, run['id']))
        connection.execute('UPDATE executions SET status=%s,evidence=%s WHERE run_id=%s',
                           (status, Jsonb({'steps': [{'step_id': 'home', 'assertion_passed': True,
                                                    'screenshot': '/stored/capture.png'}]}), run['id']))
    return store.get_run(run['id'])


def owner(store):
    actor = uuid4()
    with store.connect() as connection:
        connection.execute('INSERT INTO auth_users(id,username,display_name,password_hash,role,totp_enabled,totp_secret) '
                           "VALUES(%s,%s,'Owner','not-a-real-hash','builder',true,'test-encrypted')", (actor, 'owner-'+actor.hex))
    return actor


def schedule(recipe, enabled=True):
    return ScheduleInput(name='Keep this version', workflow_id=recipe['workflow_id'], workflow_version=1,
                         device_ids=['delete-phone'], max_concurrency=1, cron='0 9 * * *', enabled=enabled)


def wait_for_blocked_query(store, owner_pid):
    with store.connect() as connection:
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            connection.execute('SELECT pg_stat_clear_snapshot()')
            if connection.execute('SELECT 1 FROM pg_stat_activity WHERE %s=ANY(pg_blocking_pids(pid)) LIMIT 1', (owner_pid,)).fetchone():
                return
            time.sleep(0.02)
    pytest.fail('Competing query never waited for the workflow transaction')


def test_delete_preserves_definition_history_and_hides_catalog(published):
    store, recipe = published
    payload = submission(recipe)
    run = finish(store, store.submit_run(payload))
    with store.connect() as connection:
        original = connection.execute('SELECT definition,content_hash,created_at FROM workflows').fetchone()
    store.delete_workflow(recipe['workflow_id'], 1, None)
    assert store.list_workflows(100, 0) == []
    assert store.get_workflow(recipe['workflow_id'], 1)['deleted_at'] is not None
    assert store.get_run(run['id']) == run
    assert store.submit_run(payload)['id'] == run['id'], 'An accepted request still replays its exact result'
    with store.connect() as connection:
        assert connection.execute('SELECT definition,content_hash,created_at FROM workflows').fetchone() == original
        assert connection.execute('SELECT count(*) AS n FROM automation_publications').fetchone()['n'] == 1
    store.delete_workflow(recipe['workflow_id'], 1, None)
    with store.connect() as connection:
        assert connection.execute("SELECT count(*) AS n FROM audit_log WHERE action='workflow.version_deleted'").fetchone()['n'] == 1


def test_deleted_version_rejects_new_work_without_reusing_its_identity(published):
    store, recipe = published
    actor = owner(store)
    store.delete_workflow(recipe['workflow_id'], 1, actor)
    attempts = [lambda: store.submit_run(submission(recipe)),
                lambda: store.create_schedule(schedule(recipe), actor),
                lambda: store.register_workflow(WorkflowRegistration(workflow_id=recipe['workflow_id'], version=1, **recipe['definition']))]
    for attempt in attempts:
        with pytest.raises(HTTPException) as error:
            attempt()
        assert (error.value.status_code, error.value.detail) == (410, {'code': 'workflow_version_deleted'})
    with store.connect() as connection:
        assert connection.execute('SELECT count(*) AS n FROM runs').fetchone()['n'] == 0
        assert connection.execute('SELECT count(*) AS n FROM automation_schedules').fetchone()['n'] == 0
        audit = connection.execute("SELECT actor_id,metadata FROM audit_log WHERE action='workflow.version_deleted'").fetchone()
        assert audit['actor_id'] == actor
        assert audit['metadata'] == {'workflow_id': recipe['workflow_id'], 'workflow_version': 1}


@pytest.mark.parametrize('run_status,execution_status', [
    ('queued', 'queued'), ('running', 'running'), ('waiting_auth', 'waiting_auth'),
    *[('failed', status) for status in ('queued', 'leased', 'running', 'recovering', 'verifying_state', 'waiting_auth')],
])
def test_active_work_blocks_deletion_including_inconsistent_parent_state(published, run_status, execution_status):
    store, recipe = published
    run = store.submit_run(submission(recipe))
    with store.connect() as connection:
        connection.execute('UPDATE runs SET status=%s WHERE id=%s', (run_status, run['id']))
        connection.execute('UPDATE executions SET status=%s WHERE run_id=%s', (execution_status, run['id']))
    with pytest.raises(HTTPException) as error:
        store.delete_workflow(recipe['workflow_id'], 1, None)
    assert (error.value.status_code, error.value.detail) == (409, {'code': 'workflow_version_in_use'})
    assert store.get_workflow(recipe['workflow_id'], 1)['deleted_at'] is None


@pytest.mark.parametrize('enabled', [True, False])
def test_referencing_schedule_blocks_deletion_even_when_paused(published, enabled):
    store, recipe = published
    scheduled = store.create_schedule(schedule(recipe, enabled), owner(store))
    with pytest.raises(HTTPException) as error:
        store.delete_workflow(recipe['workflow_id'], 1, None)
    assert (error.value.status_code, error.value.detail) == (409, {'code': 'workflow_version_has_schedules'})
    assert store.list_schedules(100, 0)['items'][0]['id'] == scheduled['id']
    store.delete_schedule(scheduled['id'], None)
    store.delete_workflow(recipe['workflow_id'], 1, None)


def test_deleting_latest_publication_restores_draft_and_next_publish_is_new_version(published):
    store, recipe = published
    store.delete_workflow(recipe['workflow_id'], 1, None)
    draft = store.list_recipes(100, 0)['items'][0]
    assert draft['status'] == 'draft' and draft['latest_version'] == 1 and draft['revision'] == recipe['revision']
    republished = store.publish_recipe(recipe['id'], recipe['revision'], None)
    assert republished['latest_version'] == 2
    assert [version['version'] for version in store.list_workflows(100, 0)] == [2]
    assert store.get_workflow(recipe['workflow_id'], 1)['deleted_at'] is not None


def test_deleting_older_publication_does_not_invalidate_latest(published):
    store, recipe = published
    changed = store.update_recipe(recipe['id'], recipe['revision'], RecipeInput(name='New draft', steps=recipe['definition']['steps']), None)
    latest = store.publish_recipe(recipe['id'], changed['revision'], None)
    assert latest['latest_version'] == 2
    store.delete_workflow(recipe['workflow_id'], 1, None)
    assert store.list_recipes(100, 0)['items'][0]['status'] == 'published'
    assert store.publish_recipe(recipe['id'], latest['revision'], None)['latest_version'] == 2


def test_deleted_version_disables_retry_but_preserves_accepted_retry_replay(published):
    store, recipe = published
    recovery = RecoveryStore(store.dsn)
    source = finish(store, store.submit_run(submission(recipe)), 'failed')
    payload = RetryInput(request_id=uuid4(), device_ids=['delete-phone'])
    retry = recovery.retry(source['id'], payload)
    finish(store, retry, 'failed')
    store.delete_workflow(recipe['workflow_id'], 1, None)
    diagnosis = recovery.diagnosis(source['id'])['items'][0]
    assert diagnosis['can_retry'] is False and diagnosis['retry_block'] == 'workflow_version_deleted'
    assert recovery.retry(source['id'], payload)['id'] == retry['id']
    with pytest.raises(HTTPException) as error:
        recovery.retry(source['id'], RetryInput(request_id=uuid4(), device_ids=['delete-phone']))
    assert (error.value.status_code, error.value.detail) == (410, {'code': 'workflow_version_deleted'})


@pytest.mark.parametrize('role', ['admin', 'builder', 'operator', 'viewer', 'auditor'])
def test_delete_route_enforces_local_roles(auth_store, app_module, workflow_payload, role):
    user, client, _ = signed_in(auth_store, app_module, role)
    store = RunStore(auth_store.config.dsn)
    store.register_workflow(WorkflowRegistration(**workflow_payload))
    response = client.delete('/workflows/go-home/versions/1', headers={'Content-Type': 'application/json'})
    assert response.status_code == (204 if role in ('admin', 'builder') else 403), response.text
    historical = client.get('/workflows/go-home/versions/1')
    assert historical.status_code == 200
    assert bool(historical.json()['deleted_at']) == (role in ('admin', 'builder'))
    with store.connect() as connection:
        audit = connection.execute("SELECT actor_id FROM audit_log WHERE action='workflow.version_deleted'").fetchone()
        assert (str(audit['actor_id']) if audit else None) == (user['id'] if role in ('admin', 'builder') else None)


def test_delete_route_validates_identity_and_preserves_internal_versions(control_client, workflow_payload, database_dsn):
    assert control_client.delete('/workflows/missing/versions/1').status_code == 404
    assert control_client.delete('/workflows/missing/versions/0').status_code == 422
    store = RunStore(database_dsn)
    with store.connect() as connection:
        store._register_workflow(connection, WorkflowRegistration(**{**workflow_payload, 'workflow_id': 'emulator-system-protected'}), internal=True)
    assert control_client.delete('/workflows/emulator-system-protected/versions/1').status_code == 403
    assert store.get_workflow('emulator-system-protected', 1)['deleted_at'] is None


def test_concurrent_deletions_are_idempotent_and_audited_once(published):
    store, recipe = published
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: store.delete_workflow(recipe['workflow_id'], 1, None), range(4)))
    assert store.list_workflows(100, 0) == []
    with store.connect() as connection:
        assert connection.execute("SELECT count(*) AS n FROM audit_log WHERE action='workflow.version_deleted'").fetchone()['n'] == 1


def test_pending_submission_holds_version_until_queued_work_is_visible(published, monkeypatch):
    store, recipe = published
    checked, release = Event(), Event()
    owner_pid = []
    original = RunStore._available_workflow
    def paused_check(connection, workflow_id, version):
        record = original(connection, workflow_id, version)
        owner_pid.append(connection.info.backend_pid)
        checked.set()
        assert release.wait(5)
        return record
    monkeypatch.setattr(RunStore, '_available_workflow', staticmethod(paused_check))
    def remove():
        store.delete_workflow(recipe['workflow_id'], 1, None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        submitting = pool.submit(store.submit_run, submission(recipe))
        assert checked.wait(5)
        deletion = pool.submit(remove)
        try:
            wait_for_blocked_query(store, owner_pid[0])
        finally:
            release.set()
        assert submitting.result(timeout=5)['status'] == 'queued'
        with pytest.raises(HTTPException) as error:
            deletion.result(timeout=5)
        assert error.value.detail == {'code': 'workflow_version_in_use'}


def test_new_submission_waits_for_delete_commit_then_rejects(published, monkeypatch):
    store, recipe = published
    deleting, release = Event(), Event()
    owner_pid = []
    from app import run_store
    original = run_store.audit_event
    def paused_audit(*args, **kwargs):
        original(*args, **kwargs)
        owner_pid.append(args[0].info.backend_pid)
        deleting.set()
        assert release.wait(5)
    monkeypatch.setattr(run_store, 'audit_event', paused_audit)
    def submit():
        return store.submit_run(submission(recipe))
    with ThreadPoolExecutor(max_workers=2) as pool:
        deletion = pool.submit(store.delete_workflow, recipe['workflow_id'], 1, None)
        assert deleting.wait(5)
        launching = pool.submit(submit)
        try:
            wait_for_blocked_query(store, owner_pid[0])
        finally:
            release.set()
        deletion.result(timeout=5)
        with pytest.raises(HTTPException) as error:
            launching.result(timeout=5)
        assert (error.value.status_code, error.value.detail) == (410, {'code': 'workflow_version_deleted'})
