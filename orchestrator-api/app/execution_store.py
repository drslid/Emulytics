"""Fenced local-worker state. Callers hold the host device lock while owning a lease."""

from contextlib import contextmanager
from uuid import UUID, uuid4

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .run_store import RunStore


ACTIVE = ('leased', 'running', 'recovering', 'verifying_state', 'waiting_auth')
TERMINAL = ('succeeded', 'failed', 'cancelled', 'needs_review')


class ExecutionStore(RunStore):
    def cancel_run(self, run_id):
        with self.connect() as connection:
            run = connection.execute('SELECT * FROM runs WHERE id = %s FOR UPDATE', (run_id,)).fetchone()
            if run is None:
                raise HTTPException(404, 'Run not found')
            if run['status'] == 'cancelled':
                return self._read_run(connection, run_id)
            executions = connection.execute('SELECT * FROM executions WHERE run_id = %s', (run_id,)).fetchall()
            active = [row for row in executions if row['status'] in ACTIVE]
            if any(row['status'] not in (*ACTIVE, 'queued', 'succeeded', 'failed', 'cancelled') for row in executions):
                raise HTTPException(409, 'Run requires review before cancellation can be resolved')
            if active:
                owned = connection.execute(
                    'SELECT count(*) AS count FROM device_leases WHERE execution_id = ANY(%s) '
                    'AND owner_id IS NOT NULL AND expires_at > clock_timestamp() AND NOT quarantined',
                    ([row['id'] for row in active],),
                ).fetchone()['count']
                if owned != len(active):
                    raise HTTPException(409, 'Active execution has no confirmed live owner')
            elif not any(row['status'] == 'queued' for row in executions):
                raise HTTPException(409, 'Run has already finished')
            if not run['cancel_requested']:
                connection.execute('UPDATE runs SET cancel_requested = true WHERE id = %s', (run_id,))
                connection.execute(
                    "UPDATE executions SET status = 'cancelled', finished_at = clock_timestamp(), "
                    "updated_at = clock_timestamp() WHERE run_id = %s AND status = 'queued'", (run_id,),
                )
                self._aggregate(connection, run_id)
                self._event(connection, run_id, 'run.cancel_requested' if active else 'run.cancelled', {})
            return self._read_run(connection, run_id)

    def list_actions(self, execution_id, limit, offset):
        with self.connect() as connection:
            if not connection.execute('SELECT 1 FROM executions WHERE id = %s', (execution_id,)).fetchone():
                raise HTTPException(404, 'Execution not found')
            return connection.execute(
                'SELECT * FROM action_journal WHERE execution_id = %s ORDER BY started_at, id LIMIT %s OFFSET %s',
                (execution_id, limit, offset),
            ).fetchall()

    @contextmanager
    def connect(self):
        # The independent host watchdog remains authoritative if networking stalls.
        with psycopg.connect(
            self.dsn, connect_timeout=2, row_factory=dict_row, tcp_user_timeout=2000,
            keepalives_idle=2, keepalives_interval=1, keepalives_count=2,
        ) as connection:
            connection.execute("SET LOCAL statement_timeout = '2s'")
            connection.execute("SET LOCAL lock_timeout = '1s'")
            yield connection

    @staticmethod
    def _event(connection, run_id, event_type, payload):
        # Every writer holds the parent run lock before allocating its sequence.
        connection.execute(
            "INSERT INTO run_events (run_id, sequence, type, payload) "
            "SELECT %s, COALESCE(MAX(sequence), 0) + 1, %s, %s FROM run_events WHERE run_id = %s",
            (run_id, event_type, Jsonb(payload), run_id),
        )

    @staticmethod
    def _aggregate(connection, run_id):
        states = [row['status'] for row in connection.execute(
            'SELECT status FROM executions WHERE run_id = %s', (run_id,)
        ).fetchall()]
        if any(state in ACTIVE for state in states):
            status = 'running'
        elif 'queued' in states:
            status = 'running' if any(state != 'queued' for state in states) else 'queued'
        elif 'needs_review' in states:
            status = 'needs_review'
        elif 'failed' in states:
            status = 'failed'
        elif 'cancelled' in states:
            status = 'cancelled'
        else:
            status = 'succeeded'
        connection.execute('UPDATE runs SET status = %s, updated_at = clock_timestamp() WHERE id = %s', (status, run_id))

    @staticmethod
    def _lock(connection, execution_id, *, skip_locked=False):
        execution = connection.execute(
            'SELECT e.*, d.serial, d.host_id FROM executions e JOIN devices d USING (device_id) WHERE e.id = %s',
            (execution_id,),
        ).fetchone()
        if execution is None:
            return None
        suffix = ' SKIP LOCKED' if skip_locked else ''
        run = connection.execute('SELECT * FROM runs WHERE id = %s FOR UPDATE' + suffix, (execution['run_id'],)).fetchone()
        if run is None:
            return None
        # Re-read after the run lock; a preceding owner may just have finished.
        execution.update(connection.execute('SELECT * FROM executions WHERE id = %s', (execution_id,)).fetchone())
        lease = connection.execute(
            'SELECT *, expires_at > clock_timestamp() AS live FROM device_leases WHERE device_id = %s FOR UPDATE',
            (execution['device_id'],),
        ).fetchone()
        return execution, run, lease

    @staticmethod
    def _owns(locked, owner_id, epoch):
        if locked is None:
            return False
        execution, _, lease = locked
        return bool(lease and lease['owner_id'] == owner_id and lease['lease_epoch'] == epoch
                    and lease['execution_id'] == execution['id'] and lease['live']
                    and not lease['quarantined'] and execution['status'] in ACTIVE)

    @staticmethod
    def _before_deadline(connection, expires_at):
        # Retain the original deadline: a slow renewal must not resurrect its lease.
        return connection.execute(
            'SELECT %s > clock_timestamp() AS live', (expires_at,),
        ).fetchone()['live']

    def candidates(self, host_id: str, limit: int = 10):
        self.reconcile_expired(host_id)
        with self.connect() as connection:
            return connection.execute(
                "SELECT e.*, d.serial, d.host_id FROM executions e JOIN devices d USING (device_id) "
                "JOIN runs r ON r.id = e.run_id LEFT JOIN device_leases l USING (device_id) "
                "WHERE d.host_id = %s AND e.status = 'queued' AND NOT r.cancel_requested "
                "AND (l.device_id IS NULL OR (l.owner_id IS NULL AND NOT l.quarantined)) "
                "AND (SELECT count(*) FROM executions active WHERE active.run_id = r.id "
                "AND active.status = ANY(%s)) < r.max_concurrency "
                "ORDER BY e.created_at, e.id LIMIT %s", (host_id, list(ACTIVE), limit),
            ).fetchall()

    def claim(self, execution_id: UUID, owner_id: str, ttl_seconds: int, *, host_id: str | None = None):
        if not owner_id or not 1 <= ttl_seconds <= 300:
            raise ValueError('An owner and a lease TTL between 1 and 300 seconds are required')
        with self.connect() as connection:
            locked = self._lock(connection, execution_id, skip_locked=True)
            if locked is None:
                return None
            execution, run, lease = locked
            if execution['status'] != 'queued' or run['cancel_requested'] or (host_id and execution['host_id'] != host_id):
                return None
            active = connection.execute(
                'SELECT count(*) AS count FROM executions WHERE run_id = %s AND status = ANY(%s)',
                (run['id'], list(ACTIVE)),
            ).fetchone()['count']
            if active >= run['max_concurrency'] or (lease and (lease['owner_id'] is not None or lease['quarantined'])):
                return None
            connection.execute('INSERT INTO device_leases (device_id) VALUES (%s) ON CONFLICT DO NOTHING', (execution['device_id'],))
            # Another run can concurrently insert the first lease while holding its own run lock.
            lease = connection.execute(
                'SELECT * FROM device_leases WHERE device_id = %s FOR UPDATE', (execution['device_id'],)
            ).fetchone()
            if lease['owner_id'] is not None or lease['quarantined']:
                return None
            lease = connection.execute(
                "UPDATE device_leases SET lease_epoch = lease_epoch + 1, owner_id = %s, execution_id = %s, "
                "expires_at = clock_timestamp() + %s * interval '1 second' WHERE device_id = %s RETURNING *",
                (owner_id, execution_id, ttl_seconds, execution['device_id']),
            ).fetchone()
            connection.execute(
                "UPDATE executions SET status = 'running', lease_epoch = %s, started_at = clock_timestamp(), "
                "updated_at = clock_timestamp() WHERE id = %s", (lease['lease_epoch'], execution_id),
            )
            self._aggregate(connection, run['id'])
            self._event(connection, run['id'], 'execution.started', {
                'execution_id': str(execution_id), 'device_id': execution['device_id'], 'lease_epoch': lease['lease_epoch'],
            })
            workflow = connection.execute(
                'SELECT definition FROM workflows WHERE workflow_id = %s AND version = %s',
                (run['workflow_id'], run['workflow_version']),
            ).fetchone()['definition']
            return {'execution_id': execution_id, 'run_id': run['id'], 'device_id': execution['device_id'],
                    'host_id': execution['host_id'], 'serial': execution['serial'], 'owner_id': owner_id,
                    'lease_epoch': lease['lease_epoch'], 'expires_at': lease['expires_at'],
                    'workflow': workflow, 'parameters': run['parameters']}

    def state(self, execution_id, owner_id, epoch):
        with self.connect() as connection:
            state = connection.execute(
                'SELECT r.cancel_requested, l.expires_at, '
                '(l.owner_id = %s AND l.lease_epoch = %s AND l.execution_id = e.id '
                'AND l.expires_at > clock_timestamp() AND NOT l.quarantined AND e.status = ANY(%s)) AS valid '
                'FROM executions e JOIN runs r ON r.id = e.run_id LEFT JOIN device_leases l USING (device_id) '
                'WHERE e.id = %s', (owner_id, epoch, list(ACTIVE), execution_id),
            ).fetchone()
            if state is None:
                return {'valid': False, 'cancel_requested': False, 'expires_at': None}
            state['valid'] = bool(state['valid'])
            return state

    def renew(self, execution_id, owner_id, epoch, ttl_seconds):
        if not 1 <= ttl_seconds <= 300:
            raise ValueError('Lease TTL must be between 1 and 300 seconds')
        with self.connect() as connection:
            locked = self._lock(connection, execution_id)
            if not self._owns(locked, owner_id, epoch) or locked[1]['cancel_requested']:
                return False
            updated = connection.execute(
                "UPDATE device_leases SET expires_at = clock_timestamp() + %s * interval '1 second' "
                "WHERE device_id = %s AND owner_id = %s AND lease_epoch = %s AND execution_id = %s "
                "AND expires_at > clock_timestamp() AND NOT quarantined RETURNING device_id",
                (ttl_seconds, locked[0]['device_id'], owner_id, epoch, execution_id),
            ).fetchone()
            if updated is None or not self._before_deadline(connection, locked[2]['expires_at']):
                connection.rollback()
                return False
            return True

    def before_action(self, execution_id, owner_id, epoch, step_id, action, non_idempotent):
        with self.connect() as connection:
            locked = self._lock(connection, execution_id)
            if not self._owns(locked, owner_id, epoch) or locked[1]['cancel_requested']:
                return None
            journal_id = uuid4()
            inserted = connection.execute(
                'INSERT INTO action_journal (id, execution_id, step_id, lease_epoch, action, non_idempotent) '
                'SELECT %s, %s, %s, %s, %s, %s FROM device_leases '
                'WHERE device_id = %s AND owner_id = %s AND lease_epoch = %s AND execution_id = %s '
                'AND expires_at > clock_timestamp() AND NOT quarantined RETURNING id',
                (journal_id, execution_id, step_id, epoch, Jsonb(action), non_idempotent,
                 locked[0]['device_id'], owner_id, epoch, execution_id),
            ).fetchone()
            if inserted is None:
                return None
            self._event(connection, locked[1]['id'], 'action.intent', {
                'execution_id': str(execution_id), 'journal_id': str(journal_id), 'step_id': step_id, 'lease_epoch': epoch,
            })
            if not self._before_deadline(connection, locked[2]['expires_at']):
                connection.rollback()
                return None
            return journal_id

    def finish_action(self, execution_id, owner_id, epoch, journal_id, status='done', evidence=None):
        if status not in ('done', 'failed', 'cancelled', 'uncertain'):
            raise ValueError('Invalid action result')
        with self.connect() as connection:
            locked = self._lock(connection, execution_id)
            if not self._owns(locked, owner_id, epoch):
                return False
            updated = connection.execute(
                "UPDATE action_journal j SET status = %s, evidence = %s, finished_at = clock_timestamp() "
                "WHERE id = %s AND execution_id = %s AND lease_epoch = %s AND status = 'intent' "
                "AND EXISTS (SELECT 1 FROM device_leases l WHERE l.execution_id = j.execution_id "
                "AND l.owner_id = %s AND l.lease_epoch = %s AND l.expires_at > clock_timestamp() "
                "AND NOT l.quarantined) RETURNING step_id",
                (status, Jsonb(evidence or {}), journal_id, execution_id, epoch, owner_id, epoch),
            ).fetchone()
            if updated is None:
                return False
            self._event(connection, locked[1]['id'], 'action.' + status, {
                'execution_id': str(execution_id), 'journal_id': str(journal_id), 'step_id': updated['step_id'], 'lease_epoch': epoch,
            })
            if not self._before_deadline(connection, locked[2]['expires_at']):
                connection.rollback()
                return False
            return True

    def finish(self, execution_id, owner_id, epoch, status, error=None, evidence=None):
        if status not in TERMINAL:
            raise ValueError('Invalid execution result')
        with self.connect() as connection:
            locked = self._lock(connection, execution_id)
            if not self._owns(locked, owner_id, epoch):
                return False
            execution, run, _ = locked
            uncertain = connection.execute(
                "SELECT 1 FROM action_journal WHERE execution_id = %s AND status IN ('intent', 'uncertain') LIMIT 1",
                (execution_id,),
            ).fetchone()
            if uncertain:
                status = 'needs_review'
            if run['cancel_requested'] and status == 'succeeded':
                status = 'cancelled'
            updated = connection.execute(
                'UPDATE executions e SET status = %s, error = %s, evidence = %s, finished_at = clock_timestamp(), '
                'updated_at = clock_timestamp() WHERE id = %s '
                'AND EXISTS (SELECT 1 FROM device_leases l WHERE l.execution_id = e.id '
                'AND l.owner_id = %s AND l.lease_epoch = %s AND l.expires_at > clock_timestamp() '
                'AND NOT l.quarantined) RETURNING id',
                (status, error, Jsonb(evidence or {}), execution_id, owner_id, epoch),
            ).fetchone()
            if updated is None:
                return False
            if uncertain:
                connection.execute(
                    "UPDATE action_journal SET status = 'uncertain', finished_at = clock_timestamp() "
                    "WHERE execution_id = %s AND status = 'intent'", (execution_id,),
                )
            released = connection.execute(
                'UPDATE device_leases SET owner_id = NULL, execution_id = NULL, expires_at = NULL, '
                'quarantined = %s WHERE device_id = %s AND owner_id = %s AND lease_epoch = %s '
                'AND execution_id = %s AND expires_at > clock_timestamp() RETURNING device_id',
                (status == 'needs_review', execution['device_id'], owner_id, epoch, execution_id),
            ).fetchone()
            if released is None:
                connection.rollback()
                return False
            self._aggregate(connection, run['id'])
            self._event(connection, run['id'], 'execution.finished', {
                'execution_id': str(execution_id), 'device_id': execution['device_id'], 'lease_epoch': epoch, 'status': status,
            })
            if not self._before_deadline(connection, locked[2]['expires_at']):
                connection.rollback()
                return False
            return True

    def reconcile_expired(self, host_id):
        with self.connect() as connection:
            expired = connection.execute(
                'SELECT l.execution_id FROM device_leases l JOIN devices d USING (device_id) '
                'WHERE d.host_id = %s AND l.owner_id IS NOT NULL AND l.expires_at <= clock_timestamp()', (host_id,),
            ).fetchall()
        count = 0
        for row in expired:
            with self.connect() as connection:
                locked = self._lock(connection, row['execution_id'], skip_locked=True)
                if locked is None or not locked[2] or locked[2]['live'] or locked[2]['owner_id'] is None:
                    continue
                execution, run, lease = locked
                if lease['execution_id'] != execution['id']:
                    continue
                connection.execute(
                    "UPDATE action_journal SET status = 'uncertain', finished_at = clock_timestamp() "
                    "WHERE execution_id = %s AND status = 'intent'", (execution['id'],),
                )
                connection.execute(
                    "UPDATE executions SET status = 'needs_review', error = 'Lease expired; device quarantined', "
                    "finished_at = clock_timestamp(), updated_at = clock_timestamp() WHERE id = %s", (execution['id'],),
                )
                connection.execute(
                    'UPDATE device_leases SET owner_id = NULL, execution_id = NULL, expires_at = NULL, '
                    'quarantined = true WHERE device_id = %s', (execution['device_id'],),
                )
                self._aggregate(connection, run['id'])
                self._event(connection, run['id'], 'execution.needs_review', {
                    'execution_id': str(execution['id']), 'device_id': execution['device_id'], 'lease_epoch': lease['lease_epoch'],
                })
                count += 1
        return count
