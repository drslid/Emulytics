"""Evidence-based diagnosis and explicitly requested retries of safe failed devices."""
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from .access import audit_event, permissions_for
from .execution_store import ACTIVE, ExecutionStore
from .run_models import Contract, Identifier, RunSubmission
from .run_routes import ControlRoute, Store
from .run_store import RunStore, fingerprint

router = APIRouter(tags=['Run diagnosis and controlled retry'], route_class=ControlRoute)


class RetryInput(Contract):
    request_id: UUID = Field(strict=False)
    device_ids: list[Identifier] = Field(min_length=1, max_length=100)


def diagnosis_code(execution, actions, steps):
    if execution['status'] == 'needs_review' or any(row['status'] in ('uncertain', 'intent') for row in actions):
        return 'uncertain_effect'
    error = (execution.get('error') or '').lower()
    if 'package' in error and any(word in error for word in ('missing', 'installed', 'artifact')):
        return 'application_missing'
    if any(word in error for word in ('offline', 'unauthorized', 'no devices', 'device not found', 'connection refused')):
        return 'device_connection'
    if any(word in error for word in ('selector', 'node', 'element')):
        return 'element_not_found'
    if any(word in error for word in ('assert', 'expected', 'does not match')):
        return 'result_not_verified'
    if 'timeout' in error or 'timed out' in error or 'deadline' in error:
        return 'timeout'
    return 'execution_failed' if execution['status'] == 'failed' else execution['status']


class RecoveryStore(RunStore):
    @staticmethod
    def _retry_block(connection, execution, steps):
        if execution['status'] != 'failed':
            return 'only_failed'
        if any(step.get('non_idempotent') for step in steps):
            return 'non_idempotent_workflow'
        journal = connection.execute('SELECT status,non_idempotent FROM action_journal WHERE execution_id=%s', (execution['id'],)).fetchall()
        if any(row['status'] in ('intent', 'uncertain') or row['non_idempotent'] for row in journal):
            return 'uncertain_effect'
        lease = connection.execute('SELECT * FROM device_leases WHERE device_id=%s', (execution['device_id'],)).fetchone()
        if lease and (lease['quarantined'] or lease['owner_id']):
            return 'device_reserved'
        if connection.execute('SELECT 1 FROM executions WHERE device_id=%s AND status=ANY(%s) LIMIT 1',
                (execution['device_id'], ['queued', *ACTIVE])).fetchone():
            return 'device_reserved'
        return None

    def diagnosis(self, run_id):
        with self.connect() as connection:
            run = self._read_run(connection, run_id)
            definition = connection.execute('SELECT definition FROM workflows WHERE workflow_id=%s AND version=%s',
                (run['workflow_id'], run['workflow_version'])).fetchone()['definition']
            steps = definition['steps']
            internal = run['workflow_id'].startswith('emulator-system-')
            active = any(e['status'] in ('queued', *ACTIVE) for e in run['executions'])
            child = connection.execute('SELECT r.id FROM run_retries rr JOIN runs r ON r.id=rr.retry_run_id '
                "WHERE rr.source_run_id=%s AND r.status IN ('queued','running','waiting_auth') LIMIT 1", (run_id,)).fetchone()
            items = []
            for execution in run['executions']:
                actions = connection.execute('SELECT status,non_idempotent FROM action_journal WHERE execution_id=%s', (execution['id'],)).fetchall()
                block = 'managed_operation' if internal else 'source_active' if active else 'retry_active' if child else self._retry_block(connection, execution, steps)
                evidence = execution.get('evidence') or {}
                captures = evidence.get('steps', [])
                items.append({'execution_id': execution['id'], 'device_id': execution['device_id'],
                    'code': diagnosis_code(execution, actions, steps), 'failed_step': evidence.get('failed_step'),
                    'last_capture_step': next((row.get('step_id') for row in reversed(captures) if row.get('screenshot')), None),
                    'can_retry': block is None, 'retry_block': block})
            parent = connection.execute('SELECT source_run_id FROM run_retries WHERE retry_run_id=%s', (run_id,)).fetchone()
            return {'run_id': run_id, 'items': items, 'source_run_id': parent['source_run_id'] if parent else None,
                    'active_retry_id': child['id'] if child else None}

    def retry(self, run_id, payload, actor=None):
        if len(set(payload.device_ids)) != len(payload.device_ids):
            raise HTTPException(422, 'Sélectionnez chaque appareil une seule fois')
        request_hash = fingerprint({'source': str(run_id), 'device_ids': payload.device_ids})
        with self.connect() as connection:
            if actor:
                user = connection.execute('SELECT active,totp_enabled,password_change_required,role FROM auth_users WHERE id=%s FOR SHARE', (actor,)).fetchone()
                if not user or not user['active'] or not user['totp_enabled'] or user['password_change_required'] or 'runs.execute' not in permissions_for(user['role']):
                    raise HTTPException(403, 'Execution permission required')
            connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('retry:' + str(payload.request_id),))
            source = connection.execute('SELECT * FROM runs WHERE id=%s FOR UPDATE', (run_id,)).fetchone()
            if not source:
                raise HTTPException(404, 'Exécution introuvable')
            previous = connection.execute('SELECT * FROM run_retries WHERE request_id=%s', (payload.request_id,)).fetchone()
            if previous:
                if previous['request_hash'] != request_hash or previous['actor_id'] != actor:
                    raise HTTPException(409, 'Cette demande de relance correspond à un autre lot')
                return self._read_run(connection, previous['retry_run_id'])
            if connection.execute('SELECT 1 FROM runs WHERE idempotency_key=%s', (f'retry:{payload.request_id}',)).fetchone():
                raise HTTPException(409, 'Cette clé est déjà utilisée par une demande antérieure')
            if source['status'] not in ('failed', 'cancelled', 'succeeded', 'needs_review') or source['workflow_id'].startswith('emulator-system-'):
                raise HTTPException(409, 'Cette exécution ne peut pas être relancée ici')
            if connection.execute('SELECT 1 FROM run_retries rr JOIN runs r ON r.id=rr.retry_run_id '
                    "WHERE rr.source_run_id=%s AND r.status IN ('queued','running','waiting_auth')", (run_id,)).fetchone():
                raise HTTPException(409, 'Une relance de cette exécution est déjà en cours')
            steps = connection.execute('SELECT definition FROM workflows WHERE workflow_id=%s AND version=%s',
                (source['workflow_id'], source['workflow_version'])).fetchone()['definition']['steps']
            # Same device locking order as submission/allocation prevents competing work passing this check.
            connection.execute('SELECT device_id FROM devices WHERE device_id=ANY(%s) ORDER BY device_id FOR UPDATE', (payload.device_ids,)).fetchall()
            executions = connection.execute('SELECT * FROM executions WHERE run_id=%s ORDER BY attempt DESC', (run_id,)).fetchall()
            if any(row['status'] in ('queued', *ACTIVE) for row in executions):
                raise HTTPException(409, 'Attendez la fin du lot avant de relancer ses échecs')
            chosen = []
            for device in payload.device_ids:
                execution = next((row for row in executions if row['device_id'] == device), None)
                if execution is None or self._retry_block(connection, execution, steps):
                    raise HTTPException(409, 'Un appareil sélectionné exige une vérification ou ne correspond pas à un échec relançable')
                chosen.append(execution)
            submission = RunSubmission.model_validate({
                'workflow_id': source['workflow_id'], 'workflow_version': source['workflow_version'],
                'device_ids': payload.device_ids, 'max_concurrency': min(source['max_concurrency'], len(payload.device_ids)),
                'parameters': source['parameters'], 'idempotency_key': f'retry:{payload.request_id}',
            })
            result = self._submit_run(connection, submission)
            connection.execute('INSERT INTO run_retries(source_run_id,retry_run_id,request_id,actor_id,request_hash) VALUES(%s,%s,%s,%s,%s)',
                (run_id, result['id'], payload.request_id, actor, request_hash))
            for execution in chosen:
                connection.execute('UPDATE executions SET attempt=%s WHERE run_id=%s AND device_id=%s',
                    (execution['attempt'] + 1, result['id'], execution['device_id']))
            ExecutionStore._event(connection, run_id, 'run.retry_created', {'retry_run_id': str(result['id']), 'device_count': len(chosen)})
            ExecutionStore._event(connection, result['id'], 'run.retry_of', {'source_run_id': str(run_id)})
            audit_event(connection, actor, 'run.retry.created', str(result['id']), {'run_id': str(run_id), 'device_count': len(chosen)}, category='automation')
            return self._read_run(connection, result['id'])


@router.get('/runs/{run_id}/diagnosis')
def diagnosis(run_id: UUID, store: Store):
    return RecoveryStore(store.dsn).diagnosis(run_id)


@router.post('/runs/{run_id}/retry', status_code=202)
def retry(run_id: UUID, payload: RetryInput, request: Request, store: Store):
    user = getattr(request.state, 'auth_user', None)
    return RecoveryStore(store.dsn).retry(run_id, payload, UUID(str(user['id'])) if user else None)
