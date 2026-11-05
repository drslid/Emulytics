from concurrent.futures import ThreadPoolExecutor
import psycopg
import pytest

from app.execution_store import ExecutionStore
from app.run_models import RunSubmission
from app.run_store import RunStore


def rows(dsn, query, values=()):
    with psycopg.connect(dsn) as connection:
        return connection.execute(query, values).fetchall()


@pytest.fixture
def pending(registered, database_dsn, run_payload):
    run = RunStore(database_dsn).submit_run(RunSubmission.model_validate(run_payload))
    return ExecutionStore(database_dsn), run


def test_claim_grants_one_owner_and_persists_execution_event(pending, database_dsn):
    store, run = pending
    execution_id = run['executions'][0]['id']
    grant = store.claim(execution_id, 'worker-1', 30)
    assert grant['execution_id'] == execution_id
    assert grant['run_id'] == run['id']
    assert grant['serial'] == 'emulator-5554'
    assert grant['host_id'] == 'host-1'
    assert grant['lease_epoch'] == 1
    assert grant['workflow']['workflow_id'] == 'go-home'
    assert store.claim(execution_id, 'worker-2', 30) is None
    assert rows(database_dsn, 'SELECT status FROM executions') == [('running',)]
    assert rows(database_dsn, 'SELECT status FROM runs') == [('running',)]
    assert rows(database_dsn, 'SELECT type FROM run_events ORDER BY sequence') == [('run.created',), ('execution.started',)]


def test_concurrent_claims_have_one_winner(pending):
    store, run = pending
    execution_id = run['executions'][0]['id']
    with ThreadPoolExecutor(max_workers=8) as executor:
        claims = list(executor.map(lambda number: store.claim(execution_id, f'worker-{number}', 30), range(8)))
    assert len([claim for claim in claims if claim]) == 1


def test_candidates_target_host_and_omit_busy_devices(pending):
    store, run = pending
    execution_id = run['executions'][0]['id']
    assert [row['id'] for row in store.candidates('host-1')] == [execution_id]
    assert store.candidates('another-host') == []
    store.claim(execution_id, 'worker-1', 30)
    assert store.candidates('host-1') == []


def test_run_concurrency_limit_is_enforced_across_devices(pending, registered, database_dsn, run_payload):
    store, _ = pending
    assert registered.post('/devices', json={
        'device_id': 'phone-2', 'host_id': 'host-1', 'serial': 'emulator-5556', 'kind': 'emulator',
    }).status_code == 201
    submission = {**run_payload, 'idempotency_key': 'two-phones', 'device_ids': ['phone-1', 'phone-2']}
    run = RunStore(database_dsn).submit_run(RunSubmission.model_validate(submission))
    first, second = run['executions']
    assert store.claim(first['id'], 'worker-1', 30)
    assert store.claim(second['id'], 'worker-2', 30) is None
    assert store.finish(first['id'], 'worker-1', 1, 'succeeded')
    assert store.claim(second['id'], 'worker-2', 30)


def test_heartbeat_and_state_reject_stale_owner_epoch_and_expired_lease(pending, database_dsn):
    store, run = pending
    execution_id = run['executions'][0]['id']
    store.claim(execution_id, 'worker-1', 30)
    assert store.state(execution_id, 'worker-1', 1)['valid'] is True
    assert store.renew(execution_id, 'worker-1', 1, 30)
    assert not store.renew(execution_id, 'worker-2', 1, 30)
    assert not store.renew(execution_id, 'worker-1', 2, 30)
    with psycopg.connect(database_dsn) as connection:
        connection.execute("UPDATE device_leases SET expires_at = clock_timestamp() - interval '1 second'")
    assert store.state(execution_id, 'worker-1', 1)['valid'] is False
    assert not store.renew(execution_id, 'worker-1', 1, 30)
    assert not store.finish(execution_id, 'worker-1', 1, 'succeeded')


def test_durable_intention_and_proof_are_fenced(pending, database_dsn):
    store, run = pending
    execution_id = run['executions'][0]['id']
    store.claim(execution_id, 'worker-1', 30)
    journal_id = store.before_action(execution_id, 'worker-1', 1, 'home', {'command': 'press_key'}, False)
    assert rows(database_dsn, 'SELECT status FROM action_journal WHERE id = %s', (journal_id,)) == [('intent',)]
    assert not store.finish_action(execution_id, 'worker-2', 1, journal_id, 'done', {'screen': 'home'})
    assert store.finish_action(execution_id, 'worker-1', 1, journal_id, 'done', {'screen': 'home'})
    assert rows(database_dsn, 'SELECT status, evidence FROM action_journal WHERE id = %s', (journal_id,)) == [('done', {'screen': 'home'})]
    assert store.before_action(execution_id, 'worker-2', 1, 'next', {}, False) is None


def test_cancel_flag_blocks_new_actions_but_allows_confirmed_neutralization(pending, database_dsn):
    store, run = pending
    execution_id = run['executions'][0]['id']
    store.claim(execution_id, 'worker-1', 30)
    with psycopg.connect(database_dsn) as connection:
        connection.execute('UPDATE runs SET cancel_requested = true WHERE id = %s', (run['id'],))
    assert store.state(execution_id, 'worker-1', 1) == {
        **store.state(execution_id, 'worker-1', 1), 'valid': True, 'cancel_requested': True,
    }
    assert not store.renew(execution_id, 'worker-1', 1, 30)
    assert store.before_action(execution_id, 'worker-1', 1, 'home', {}, False) is None
    assert store.finish(execution_id, 'worker-1', 1, 'cancelled')
    assert rows(database_dsn, 'SELECT status FROM runs') == [('cancelled',)]


def test_expired_lease_quarantines_device_and_uncertain_intention(pending, database_dsn):
    store, run = pending
    execution_id = run['executions'][0]['id']
    store.claim(execution_id, 'worker-1', 30)
    store.before_action(execution_id, 'worker-1', 1, 'install', {'package': 'test'}, True)
    with psycopg.connect(database_dsn) as connection:
        connection.execute("UPDATE device_leases SET expires_at = clock_timestamp() - interval '1 second'")
    assert store.reconcile_expired('another-host') == 0
    assert store.reconcile_expired('host-1') == 1
    assert rows(database_dsn, 'SELECT status FROM executions') == [('needs_review',)]
    assert rows(database_dsn, 'SELECT status FROM action_journal') == [('uncertain',)]
    assert rows(database_dsn, 'SELECT quarantined, owner_id FROM device_leases') == [(True, None)]
    assert store.claim(execution_id, 'worker-2', 30) is None
    assert store.candidates('host-1') == []
    assert store.reconcile_expired('host-1') == 0


def test_finishing_success_releases_bail_and_increments_epoch_on_next_run(pending, database_dsn, run_payload):
    store, run = pending
    execution_id = run['executions'][0]['id']
    store.claim(execution_id, 'worker-1', 30)
    assert store.finish(execution_id, 'worker-1', 1, 'succeeded', evidence={'proof': 'screen.png'})
    assert rows(database_dsn, 'SELECT status FROM runs') == [('succeeded',)]
    assert rows(database_dsn, 'SELECT owner_id, lease_epoch FROM device_leases') == [(None, 1)]
    next_run = RunStore(database_dsn).submit_run(RunSubmission.model_validate({**run_payload, 'idempotency_key': 'next-run'}))
    grant = store.claim(next_run['executions'][0]['id'], 'worker-2', 30)
    assert grant['lease_epoch'] == 2
    assert not store.finish(execution_id, 'worker-1', 1, 'failed')


def test_uncertain_action_prevents_success_and_quarantines_device(pending, database_dsn):
    store, run = pending
    execution_id = run['executions'][0]['id']
    store.claim(execution_id, 'worker-1', 30)
    journal_id = store.before_action(execution_id, 'worker-1', 1, 'submit', {}, True)
    assert store.finish_action(execution_id, 'worker-1', 1, journal_id, 'uncertain', {})
    assert store.finish(execution_id, 'worker-1', 1, 'succeeded')
    assert rows(database_dsn, 'SELECT status FROM executions') == [('needs_review',)]
    assert rows(database_dsn, 'SELECT status FROM runs') == [('needs_review',)]
    assert rows(database_dsn, 'SELECT quarantined FROM device_leases') == [(True,)]


def test_finish_event_failure_rolls_back_state_and_lease(pending, database_dsn):
    store, run = pending
    execution_id = run['executions'][0]['id']
    store.claim(execution_id, 'worker-1', 30)
    with psycopg.connect(database_dsn) as connection:
        connection.execute("""
            CREATE FUNCTION reject_finish() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.type = 'execution.finished' THEN RAISE EXCEPTION 'injected'; END IF; RETURN NEW; END $$;
            CREATE TRIGGER reject_finish BEFORE INSERT ON run_events FOR EACH ROW EXECUTE FUNCTION reject_finish();
        """)
    with pytest.raises(psycopg.Error):
        store.finish(execution_id, 'worker-1', 1, 'succeeded')
    assert rows(database_dsn, 'SELECT status FROM executions') == [('running',)]
    assert rows(database_dsn, 'SELECT owner_id FROM device_leases') == [('worker-1',)]


def test_claim_cancelled_run_never_leases_device(pending, database_dsn):
    store, run = pending
    RunStore(database_dsn).cancel_run(run['id'])
    assert store.claim(run['executions'][0]['id'], 'worker-1', 30) is None
    assert rows(database_dsn, 'SELECT count(*) FROM device_leases') == [(0,)]


def test_different_runs_cannot_drive_the_same_device_concurrently(pending, database_dsn, run_payload):
    store, first = pending
    second = RunStore(database_dsn).submit_run(RunSubmission.model_validate({**run_payload, 'idempotency_key': 'second'}))
    execution_ids = [first['executions'][0]['id'], second['executions'][0]['id']]
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda item: store.claim(item[1], f'worker-{item[0]}', 30), enumerate(execution_ids)))
    assert sum(claim is not None for claim in claims) == 1
    assert rows(database_dsn, "SELECT count(*) FROM executions WHERE status = 'running'") == [(1,)]
    assert rows(database_dsn, 'SELECT count(*) FROM device_leases WHERE owner_id IS NOT NULL') == [(1,)]


def test_claim_does_not_reallocate_an_occupied_expired_lease(pending, database_dsn, run_payload):
    store, first = pending
    store.claim(first['executions'][0]['id'], 'worker-1', 30)
    second = RunStore(database_dsn).submit_run(RunSubmission.model_validate({**run_payload, 'idempotency_key': 'second'}))
    with psycopg.connect(database_dsn) as connection:
        connection.execute("UPDATE device_leases SET expires_at = clock_timestamp() - interval '1 second'")
    assert store.claim(second['executions'][0]['id'], 'worker-2', 30) is None
    assert rows(database_dsn, 'SELECT owner_id, lease_epoch FROM device_leases') == [('worker-1', 1)]
    store.reconcile_expired('host-1')
    assert store.claim(second['executions'][0]['id'], 'worker-2', 30) is None
    assert store.candidates('host-1') == []


def test_claim_rejects_wrong_host_without_creating_a_lease(pending, database_dsn):
    store, run = pending
    assert store.claim(run['executions'][0]['id'], 'worker-1', 30, host_id='wrong-host') is None
    assert rows(database_dsn, 'SELECT count(*) FROM device_leases') == [(0,)]
    assert store.claim(run['executions'][0]['id'], 'worker-1', 30, host_id='host-1')


def test_action_proof_is_write_once_and_belongs_to_the_execution(pending, database_dsn):
    store, run = pending
    execution_id = run['executions'][0]['id']
    store.claim(execution_id, 'worker-1', 30)
    journal_id = store.before_action(execution_id, 'worker-1', 1, 'home', {}, False)
    assert store.finish_action(execution_id, 'worker-1', 1, journal_id, 'done', {'screen': 'first'})
    assert not store.finish_action(execution_id, 'worker-1', 1, journal_id, 'failed', {'screen': 'second'})
    assert rows(database_dsn, 'SELECT status, evidence FROM action_journal WHERE id = %s', (journal_id,)) == [('done', {'screen': 'first'})]


@pytest.mark.parametrize('operation', ['renew', 'before_action', 'finish_action', 'finish'])
@pytest.mark.parametrize('delay', ['after_lock', 'during_write'])
def test_owner_writes_rollback_if_lease_expires_during_transaction(pending, database_dsn, monkeypatch, operation, delay):
    store, run = pending
    execution_id = run['executions'][0]['id']
    store.claim(execution_id, 'worker-1', 30)
    journal_id = None
    if operation == 'finish_action':
        journal_id = store.before_action(execution_id, 'worker-1', 1, 'home', {}, False)
    original_actions = rows(database_dsn, 'SELECT id, status, evidence FROM action_journal')
    original_events = rows(database_dsn, 'SELECT sequence, type FROM run_events ORDER BY sequence')

    if delay == 'during_write':
        with psycopg.connect(database_dsn) as connection:
            connection.execute("""
                CREATE FUNCTION delay_owner_write() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN PERFORM pg_sleep(0.3); RETURN NEW; END $$;
            """)
            if operation == 'renew':
                connection.execute("""
                    CREATE TRIGGER delay_owner_write BEFORE UPDATE ON device_leases FOR EACH ROW
                    WHEN (NEW.expires_at > OLD.expires_at) EXECUTE FUNCTION delay_owner_write();
                """)
            else:
                connection.execute("""
                    CREATE TRIGGER delay_owner_write BEFORE INSERT ON run_events FOR EACH ROW
                    EXECUTE FUNCTION delay_owner_write();
                """)

    original_lock = store._lock

    def lock_with_short_deadline(connection, *args, **kwargs):
        with psycopg.connect(database_dsn) as setup:
            setup.execute("UPDATE device_leases SET expires_at = clock_timestamp() + interval '0.2 seconds'")
        locked = original_lock(connection, *args, **kwargs)
        assert locked[2]['live'] is True
        if delay == 'after_lock':
            connection.execute('SELECT pg_sleep(0.3)')
        return locked

    monkeypatch.setattr(store, '_lock', lock_with_short_deadline)
    if operation == 'renew':
        accepted = store.renew(execution_id, 'worker-1', 1, 30)
    elif operation == 'before_action':
        accepted = store.before_action(execution_id, 'worker-1', 1, 'next', {}, False)
    elif operation == 'finish_action':
        accepted = store.finish_action(execution_id, 'worker-1', 1, journal_id, 'done', {'proof': 'screen'})
    else:
        accepted = store.finish(execution_id, 'worker-1', 1, 'succeeded', evidence={'proof': 'screen'})

    assert not accepted
    assert rows(database_dsn, 'SELECT status, evidence FROM executions') == [('running', {})]
    assert rows(database_dsn, 'SELECT owner_id, lease_epoch FROM device_leases') == [('worker-1', 1)]
    assert rows(database_dsn, 'SELECT expires_at > clock_timestamp() FROM device_leases') == [(False,)]
    assert rows(database_dsn, 'SELECT id, status, evidence FROM action_journal') == original_actions
    assert rows(database_dsn, 'SELECT sequence, type FROM run_events ORDER BY sequence') == original_events


def test_saturated_run_does_not_hide_claimable_work(pending, database_dsn, run_payload):
    store, _ = pending
    for index in range(1, 12):
        with psycopg.connect(database_dsn) as connection:
            connection.execute(
                "INSERT INTO devices (device_id, host_id, serial, kind) VALUES (%s, 'host-1', %s, 'emulator')",
                (f'phone-{index + 1}', f'emulator-{5554 + index * 2}'),
            )
    older = store.submit_run(RunSubmission.model_validate({
        **run_payload, 'device_ids': [f'phone-{index + 1}' for index in range(11)], 'idempotency_key': 'large-run',
    }))
    assert store.claim(older['executions'][0]['id'], 'busy-worker', 30)
    later = store.submit_run(RunSubmission.model_validate({
        **run_payload, 'device_ids': ['phone-12'], 'idempotency_key': 'later-run',
    }))
    # The pending fixture also created work for the occupied phone-1.
    assert [candidate['id'] for candidate in store.candidates('host-1')] == [later['executions'][0]['id']]
    assert store.claim(later['executions'][0]['id'], 'idle-worker', 30)
