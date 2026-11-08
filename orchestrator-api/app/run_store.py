"""Transactional control-plane persistence. No allocation or device effects occur here."""

import hashlib
import json
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .access import audit_event
from .run_models import DeviceRegistration, RunSubmission, WorkflowRegistration

INTERNAL_WORKFLOW_PREFIX = 'emulator-system-'

def fingerprint(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class RunStore:
    def __init__(self, dsn: str):
        self.dsn = dsn

    @contextmanager
    def connect(self):
        with psycopg.connect(self.dsn, connect_timeout=5, row_factory=dict_row) as connection:
            connection.execute("SET LOCAL statement_timeout = '10s'")
            connection.execute("SET LOCAL lock_timeout = '5s'")
            yield connection

    def register_device(self, device: DeviceRegistration) -> tuple[dict, bool]:
        values = device.model_dump(mode="json")
        with self.connect() as connection:
            inserted = connection.execute(
                "INSERT INTO devices (device_id, host_id, serial, kind, display_name) VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING RETURNING *",
                (device.device_id, device.host_id, device.serial, device.kind, device.display_name),
            ).fetchone()
            record = inserted or connection.execute(
                "SELECT * FROM devices WHERE device_id = %s", (device.device_id,)
            ).fetchone()
            if record is None or any(record[key] != value for key, value in values.items()):
                raise HTTPException(409, "Device identity or host/serial is already registered differently")
            return record, inserted is not None

    def list_devices(self, limit: int, offset: int) -> list[dict]:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM devices ORDER BY device_id LIMIT %s OFFSET %s", (limit, offset)
            ).fetchall()

    def register_workflow(self, workflow: WorkflowRegistration) -> tuple[dict, bool]:
        with self.connect() as connection:
            return self._register_workflow(connection, workflow)

    def _register_workflow(self, connection, workflow: WorkflowRegistration, *, internal=False) -> tuple[dict, bool]:
        if workflow.workflow_id.startswith(INTERNAL_WORKFLOW_PREFIX) and not internal:
            raise HTTPException(403, 'Managed emulator workflows are reserved')
        definition = workflow.model_dump(mode="json", by_alias=True)
        for step in definition["steps"]:
            # Preserve existing immutable hashes when upgrading the optional step envelope.
            if step.get("when") is None:
                step.pop("when", None)
        content_hash = fingerprint(definition)
        inserted = connection.execute(
            "INSERT INTO workflows (workflow_id, version, definition, content_hash) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING RETURNING *",
            (workflow.workflow_id, workflow.version, Jsonb(definition), content_hash),
        ).fetchone()
        record = inserted or self._available_workflow(connection, workflow.workflow_id, workflow.version)
        if record["content_hash"] != content_hash:
            raise HTTPException(409, "Workflow version is immutable; publish a new version")
        return {**record["definition"], "created_at": record["created_at"]}, inserted is not None

    def get_workflow(self, workflow_id: str, version: int) -> dict:
        with self.connect() as connection:
            record = connection.execute(
                "SELECT w.definition,w.created_at,w.deleted_at,p.name,p.instructions FROM workflows w "
                "LEFT JOIN automation_publications p ON p.workflow_id=w.workflow_id AND p.version=w.version "
                "WHERE w.workflow_id = %s AND w.version = %s",
                (workflow_id, version),
            ).fetchone()
            if record is None:
                raise HTTPException(404, "Workflow version not found")
            return {**record["definition"], "created_at": record["created_at"], "deleted_at": record["deleted_at"], "name": record["name"], "instructions": record["instructions"]}

    @staticmethod
    def _available_workflow(connection, workflow_id: str, version: int) -> dict:
        # Share the version lock through creation so deletion cannot overtake this check.
        record = connection.execute(
            'SELECT * FROM workflows WHERE workflow_id=%s AND version=%s FOR SHARE', (workflow_id, version),
        ).fetchone()
        if record is None:
            raise HTTPException(404, 'Workflow version not found')
        if record['deleted_at'] is not None:
            raise HTTPException(410, {'code': 'workflow_version_deleted'})
        return record

    def delete_workflow(self, workflow_id: str, version: int, actor_id: UUID | None) -> None:
        if workflow_id.startswith(INTERNAL_WORKFLOW_PREFIX):
            raise HTTPException(403, 'Managed emulator workflows are reserved')
        with self.connect() as connection:
            record = connection.execute(
                'SELECT deleted_at FROM workflows WHERE workflow_id=%s AND version=%s FOR UPDATE', (workflow_id, version),
            ).fetchone()
            if record is None:
                raise HTTPException(404, 'Workflow version not found')
            if record['deleted_at'] is not None:
                return
            if connection.execute(
                'SELECT 1 FROM automation_schedules WHERE workflow_id=%s AND workflow_version=%s LIMIT 1', (workflow_id, version),
            ).fetchone():
                raise HTTPException(409, {'code': 'workflow_version_has_schedules'})
            if connection.execute(
                "SELECT 1 FROM runs r WHERE r.workflow_id=%s AND r.workflow_version=%s "
                "AND (r.status IN ('queued','running','waiting_auth') OR EXISTS(SELECT 1 FROM executions e "
                "WHERE e.run_id=r.id AND e.status IN ('queued','leased','running','recovering','verifying_state','waiting_auth'))) LIMIT 1",
                (workflow_id, version),
            ).fetchone():
                raise HTTPException(409, {'code': 'workflow_version_in_use'})
            connection.execute('UPDATE workflows SET deleted_at=clock_timestamp() WHERE workflow_id=%s AND version=%s', (workflow_id, version))
            connection.execute(
                'UPDATE automation_recipes SET published_revision=NULL,updated_at=clock_timestamp() '
                'WHERE workflow_id=%s AND latest_version=%s', (workflow_id, version),
            )
            audit_event(connection, actor_id, 'workflow.version_deleted', f'{workflow_id}:{version}',
                        {'workflow_id': workflow_id, 'workflow_version': version}, category='automation')

    def list_workflows(self, limit: int, offset: int) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT w.definition,w.created_at,p.name,p.instructions FROM workflows w "
                "LEFT JOIN automation_publications p ON p.workflow_id=w.workflow_id AND p.version=w.version "
                "WHERE w.deleted_at IS NULL AND w.workflow_id NOT LIKE %s ORDER BY w.workflow_id,w.version DESC LIMIT %s OFFSET %s",
                (INTERNAL_WORKFLOW_PREFIX+'%',limit, offset),
            ).fetchall()
            return [{**row["definition"], "created_at": row["created_at"], "name": row["name"], "instructions": row["instructions"]} for row in rows]

    @staticmethod
    def _read_run(connection, run_id: UUID) -> dict:
        # Writers lock the run first, so the detail and executions form one consistent snapshot.
        record = connection.execute("SELECT * FROM runs WHERE id = %s FOR SHARE", (run_id,)).fetchone()
        if record is None:
            raise HTTPException(404, "Run not found")
        record.pop("request_hash")
        record["run_id"] = record["id"]
        record["executions"] = connection.execute(
            "SELECT * FROM executions WHERE run_id = %s ORDER BY device_id, attempt", (run_id,)
        ).fetchall()
        return record

    def _replay_run(self, connection, key: str, request_hash: str) -> dict | None:
        previous = connection.execute(
            "SELECT id, request_hash FROM runs WHERE idempotency_key = %s", (key,)
        ).fetchone()
        if previous is None:
            return None
        if previous["request_hash"] != request_hash:
            raise HTTPException(409, "Idempotency key was already used with different content")
        return self._read_run(connection, previous["id"])

    def submit_run(self, submission: RunSubmission) -> dict:
        if submission.idempotency_key.startswith(('retry:', 'api-')):
            raise HTTPException(422, 'This idempotency key prefix is reserved for a dedicated endpoint')
        with self.connect() as connection:
            return self._submit_run(connection, submission)

    def _submit_run(self, connection, submission: RunSubmission, *, internal=False) -> dict:
        if submission.workflow_id.startswith(INTERNAL_WORKFLOW_PREFIX) and not internal:
            raise HTTPException(403, 'Managed emulator operations use their dedicated endpoint')
        request_hash = fingerprint(submission.model_dump(mode='json',exclude={'idempotency_key'}))
        replay = self._replay_run(connection,submission.idempotency_key,request_hash)
        if replay is not None:
            return replay
        self._available_workflow(connection, submission.workflow_id, submission.workflow_version)
        devices = connection.execute('SELECT device_id FROM devices WHERE device_id=ANY(%s) ORDER BY device_id FOR UPDATE',(submission.device_ids,)).fetchall()
        if len(devices)!=len(submission.device_ids):
            raise HTTPException(404,'One or more devices are not registered')
        if not internal:
            blocked = connection.execute(
                "SELECT 1 FROM managed_emulators m LEFT JOIN device_leases l USING(device_id) WHERE m.device_id=ANY(%s) "
                "AND (m.state<>'ready' OR l.quarantined OR (l.owner_id IS NOT NULL AND l.expires_at<=clock_timestamp()) "
                "OR EXISTS(SELECT 1 FROM runs last_operation WHERE last_operation.id=m.last_run_id AND last_operation.status IN ('failed','needs_review')) "
                "OR EXISTS(SELECT 1 FROM emulator_operations o JOIN executions e ON e.run_id=o.run_id WHERE o.device_id=m.device_id "
                "AND e.status IN ('queued','leased','running','recovering','verifying_state','waiting_auth'))) LIMIT 1",(submission.device_ids,),
            ).fetchone()
            if blocked:
                raise HTTPException(409,'Prepare and start the managed emulator before launching a journey')
        run_id = uuid4()
        inserted = connection.execute(
            'INSERT INTO runs(id,workflow_id,workflow_version,device_ids,max_concurrency,parameters,idempotency_key,request_hash) '
            'VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(idempotency_key) DO NOTHING RETURNING id',
            (run_id,submission.workflow_id,submission.workflow_version,Jsonb(submission.device_ids),submission.max_concurrency,Jsonb(submission.parameters),submission.idempotency_key,request_hash),
        ).fetchone()
        if inserted is None:
            return self._replay_run(connection,submission.idempotency_key,request_hash)
        with connection.cursor() as cursor:
            cursor.executemany('INSERT INTO executions(id,run_id,device_id) VALUES(%s,%s,%s)',[(uuid4(),run_id,device_id) for device_id in submission.device_ids])
        connection.execute("INSERT INTO run_events(run_id,sequence,type,payload) VALUES(%s,1,'run.created',%s)",(run_id,Jsonb({'device_count':len(submission.device_ids)})))
        return self._read_run(connection,run_id)

    def get_run(self, run_id: UUID) -> dict:
        with self.connect() as connection:
            return self._read_run(connection, run_id)

    def list_runs(self, limit: int, offset: int) -> list[dict]:
        with self.connect() as connection:
            return connection.execute(
                "SELECT id, workflow_id, workflow_version, device_ids, max_concurrency, status, "
                "cancel_requested, created_at, updated_at FROM runs "
                "ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s", (limit, offset)
            ).fetchall()

    def cancel_run(self, run_id: UUID) -> dict:
        with self.connect() as connection:
            run = connection.execute("SELECT status FROM runs WHERE id = %s FOR UPDATE", (run_id,)).fetchone()
            if run is None:
                raise HTTPException(404, "Run not found")
            if run["status"] == "cancelled":
                return self._read_run(connection, run_id)
            active = connection.execute(
                "SELECT 1 FROM executions WHERE run_id = %s AND status <> 'queued' LIMIT 1", (run_id,)
            ).fetchone()
            if run["status"] != "queued" or active:
                raise HTTPException(409, "Only fully queued runs can be cancelled by this implementation")
            connection.execute(
                "UPDATE runs SET status = 'cancelled', cancel_requested = true, updated_at = now() WHERE id = %s",
                (run_id,),
            )
            connection.execute(
                "UPDATE executions SET status = 'cancelled', updated_at = now() WHERE run_id = %s", (run_id,)
            )
            # Sequence allocation shares the run lock; a global serial is not commit order.
            connection.execute(
                "INSERT INTO run_events (run_id, sequence, type, payload) "
                "SELECT %s, COALESCE(MAX(sequence), 0) + 1, 'run.cancelled', '{}'::jsonb "
                "FROM run_events WHERE run_id = %s", (run_id, run_id)
            )
            return self._read_run(connection, run_id)

    def list_events(self, run_id: UUID, after: int, limit: int) -> list[dict]:
        with self.connect() as connection:
            if not connection.execute("SELECT 1 FROM runs WHERE id = %s", (run_id,)).fetchone():
                raise HTTPException(404, "Run not found")
            return connection.execute(
                "SELECT * FROM run_events WHERE run_id = %s AND sequence > %s ORDER BY sequence LIMIT %s",
                (run_id, after, limit),
            ).fetchall()
