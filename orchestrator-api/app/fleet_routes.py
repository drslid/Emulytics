"""Named fleet selections and individually idempotent, explicit emulator operations."""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field, field_validator, model_validator
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from .access import audit_event
from .console_routes import device_connection
from .emulator_store import EmulatorStore
from .run_models import Contract, Identifier
from .run_routes import ControlRoute, Store
from .run_store import RunStore, fingerprint

router = APIRouter(prefix='/console/fleet', tags=['Fleet groups and capacity'], route_class=ControlRoute)


class GroupInput(Contract):
    name: str = Field(min_length=1, max_length=120)
    device_ids: list[Identifier] = Field(min_length=1, max_length=100)

    @field_validator('name', mode='before')
    @classmethod
    def trim_name(cls, value):
        return ' '.join(value.split()) if isinstance(value, str) else value

    @model_validator(mode='after')
    def unique_members(self):
        if len(set(self.device_ids)) != len(self.device_ids):
            raise ValueError('Duplicate device')
        return self


class GroupUpdate(GroupInput):
    revision: int = Field(ge=1, le=2147483646)


class BulkInput(Contract):
    request_id: UUID = Field(strict=False)
    action: Literal['start', 'prepare', 'stop']
    device_ids: list[Identifier] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_devices(self):
        if len(set(self.device_ids)) != len(self.device_ids):
            raise ValueError('Duplicate device')
        return self


class FleetStore(RunStore):
    @staticmethod
    def _group(connection, group_id):
        row = connection.execute('SELECT * FROM device_groups WHERE id=%s', (group_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Groupe introuvable')
        row['device_ids'] = [item['device_id'] for item in connection.execute(
            'SELECT device_id FROM device_group_members WHERE group_id=%s ORDER BY device_id', (group_id,)).fetchall()]
        return row

    def groups(self):
        with self.connect() as connection:
            return {'items': [self._group(connection, row['id']) for row in connection.execute(
                'SELECT id FROM device_groups ORDER BY lower(name),id LIMIT 1000').fetchall()]}

    def save_group(self, payload, actor=None, group_id=None):
        with self.connect() as connection:
            if actor:
                EmulatorStore._actor(connection, actor)
            # Device removal takes these locks in the same order before changing membership.
            devices = connection.execute('SELECT device_id FROM devices WHERE device_id=ANY(%s) ORDER BY device_id FOR KEY SHARE', (payload.device_ids,)).fetchall()
            if group_id:
                row = connection.execute('SELECT revision FROM device_groups WHERE id=%s FOR UPDATE', (group_id,)).fetchone()
                if not row:
                    raise HTTPException(404, 'Groupe introuvable')
                if row['revision'] != payload.revision:
                    raise HTTPException(409, 'Ce groupe a changé. Rechargez sa fiche avant de modifier ses appareils.')
            if len(devices) != len(payload.device_ids):
                raise HTTPException(404, 'Un appareil du groupe est introuvable')
            previous = connection.execute('SELECT id FROM device_groups WHERE lower(name)=lower(%s)', (payload.name,)).fetchone()
            if previous and previous['id'] != group_id:
                raise HTTPException(409, 'Un groupe porte déjà ce nom')
            if not group_id:
                group_id = uuid4()
                # The unique index also protects concurrent requests with the same name.
                inserted = connection.execute('INSERT INTO device_groups(id,name,created_by) VALUES(%s,%s,%s) '
                    'ON CONFLICT DO NOTHING RETURNING id', (group_id, payload.name, actor)).fetchone()
                if not inserted:
                    raise HTTPException(409, 'Un groupe porte déjà ce nom')
            else:
                try:
                    connection.execute('UPDATE device_groups SET name=%s,revision=revision+1,updated_at=clock_timestamp() WHERE id=%s', (payload.name, group_id))
                except UniqueViolation:
                    raise HTTPException(409, 'Un groupe porte déjà ce nom') from None
                connection.execute('DELETE FROM device_group_members WHERE group_id=%s', (group_id,))
            with connection.cursor() as cursor:
                cursor.executemany('INSERT INTO device_group_members(group_id,device_id) VALUES(%s,%s)', [(group_id, value) for value in payload.device_ids])
            audit_event(connection, actor, 'fleet.group.saved', str(group_id), {'device_count': len(payload.device_ids)}, category='automation')
            return self._group(connection, group_id)

    def group_detail(self, group_id):
        with self.connect() as connection:
            group = self._group(connection, group_id)
            devices, _ = self.observed_devices(connection, group['device_ids'])
            return {'group': group, 'devices': devices}

    def delete_group(self, group_id, actor=None):
        with self.connect() as connection:
            if actor:
                EmulatorStore._actor(connection, actor)
            if not connection.execute('DELETE FROM device_groups WHERE id=%s RETURNING id', (group_id,)).fetchone():
                raise HTTPException(404, 'Groupe introuvable')
            audit_event(connection, actor, 'fleet.group.deleted', str(group_id), category='automation')

    @staticmethod
    def observed_devices(connection, ids=None):
        where, parameters = ('WHERE d.device_id=ANY(%s)', (ids,)) if ids is not None else ('', ())
        devices = connection.execute(
            "SELECT d.*,m.state AS emulator_state,CASE WHEN l.quarantined OR (l.owner_id IS NOT NULL AND l.expires_at<=clock_timestamp()) "
            "THEN 'needs_review' WHEN l.owner_id IS NOT NULL THEN 'busy' ELSE 'declared' END AS availability "
            "FROM devices d LEFT JOIN device_leases l USING(device_id) LEFT JOIN managed_emulators m USING(device_id) "
            + where + ' ORDER BY d.device_id', parameters).fetchall()
        workers = connection.execute("SELECT instance_id,host_id,status,metrics,last_seen_at,"
            "last_seen_at>clock_timestamp()-interval '20 seconds' AS live FROM service_heartbeats "
            "WHERE component='worker' ORDER BY last_seen_at DESC").fetchall()
        return [{**row, **device_connection(row, workers)} for row in devices], workers

    def capacity(self):
        with self.connect() as connection:
            devices, workers = self.observed_devices(connection)
            active = connection.execute("SELECT d.host_id,count(*) AS n FROM device_leases l JOIN devices d USING(device_id) "
                "WHERE l.owner_id IS NOT NULL AND l.expires_at>clock_timestamp() GROUP BY d.host_id").fetchall()
            queued = connection.execute("SELECT count(*) AS n FROM executions WHERE status='queued'").fetchone()['n']
            hosts = []
            for host in sorted({d['host_id'] for d in devices} | {w['host_id'] for w in workers if w['host_id']}):
                slots = sum(1 for w in workers if w['host_id'] == host and w['live'] and w['status'] == 'ready')
                busy = next((row['n'] for row in active if row['host_id'] == host), 0)
                ready = sum(1 for d in devices if d['host_id'] == host and d['connection_status'] == 'connected'
                    and d['availability'] == 'declared' and d['emulator_state'] in (None, 'ready'))
                hosts.append({'host_id': host, 'worker_slots': slots, 'active_slots': busy,
                              'available_slots': min(max(0, slots - busy), ready), 'ready_devices': ready})
            return {key: sum(host[key] for host in hosts) for key in ('worker_slots', 'active_slots', 'available_slots', 'ready_devices')} | {
                'connected_devices': sum(d['connection_status'] == 'connected' for d in devices), 'queued_executions': queued,
                'hosts': hosts, 'observed_at': datetime.now(timezone.utc), 'capacity_basis': 'one_execution_per_live_worker'}

    def bulk(self, payload, actor=None):
        values = {'action': payload.action, 'device_ids': payload.device_ids}
        request_hash = fingerprint(values)
        # Commit the immutable intent before the first per-device operation can be accepted.
        with self.connect() as connection:
            connection.execute('INSERT INTO fleet_bulk_requests(request_id,actor_id,request_hash,action) VALUES(%s,%s,%s,%s) '
                'ON CONFLICT DO NOTHING', (payload.request_id, actor, request_hash, payload.action))
            row = connection.execute('SELECT * FROM fleet_bulk_requests WHERE request_id=%s', (payload.request_id,)).fetchone()
            if row['actor_id'] != actor or row['request_hash'] != request_hash:
                raise HTTPException(409, 'Cette demande groupée correspond à une autre sélection ou action')
        with self.connect() as guard:
            lock = int(payload.request_id.hex[:15], 16)
            if not guard.execute('SELECT pg_try_advisory_xact_lock(%s) AS ok', (lock,)).fetchone()['ok']:
                raise HTTPException(409, 'Cette demande groupée est en cours. Vérifiez à nouveau son résultat.')
            for device in payload.device_ids:
                with self.connect() as connection:
                    row = connection.execute('SELECT results FROM fleet_bulk_requests WHERE request_id=%s', (payload.request_id,)).fetchone()
                if device in row['results']:
                    continue
                key = f'fleet:{payload.request_id}:{fingerprint({"device": device})[:20]}'
                try:
                    value = EmulatorStore(self.dsn).queue_operation(device, payload.action, key, actor)
                    item = {'device_id': device, 'status': 'accepted', 'run_id': str(value['run_id'])}
                except HTTPException as error:
                    if error.status_code >= 500:
                        raise  # The outcome is not definitive; keep the same intent for recovery.
                    item = {'device_id': device, 'status': 'rejected', 'detail': str(error.detail)}
                with self.connect() as connection:
                    connection.execute('UPDATE fleet_bulk_requests SET results=results||%s WHERE request_id=%s',
                        (Jsonb({device: item}), payload.request_id))
            with self.connect() as connection:
                row = connection.execute('SELECT results FROM fleet_bulk_requests WHERE request_id=%s', (payload.request_id,)).fetchone()
            return {'request_id': payload.request_id, 'action': payload.action, 'items': [row['results'][device] for device in payload.device_ids]}


def actor(request):
    user = getattr(request.state, 'auth_user', None)
    return UUID(str(user['id'])) if user else None


@router.get('/groups')
def groups(store: Store):
    return FleetStore(store.dsn).groups()


@router.post('/groups', status_code=201)
def save_group(payload: GroupInput, request: Request, store: Store):
    return FleetStore(store.dsn).save_group(payload, actor(request))


@router.get('/groups/{group_id}')
def group_detail(group_id: UUID, store: Store):
    return FleetStore(store.dsn).group_detail(group_id)


@router.patch('/groups/{group_id}')
def update_group(group_id: UUID, payload: GroupUpdate, request: Request, store: Store):
    return FleetStore(store.dsn).save_group(payload, actor(request), group_id)


@router.delete('/groups/{group_id}', status_code=204)
def delete_group(group_id: UUID, request: Request, store: Store):
    FleetStore(store.dsn).delete_group(group_id, actor(request))
    return Response(status_code=204)


@router.get('/capacity')
def capacity(store: Store):
    return FleetStore(store.dsn).capacity()


@router.post('/bulk')
def bulk(payload: BulkInput, request: Request, store: Store):
    return FleetStore(store.dsn).bulk(payload, actor(request))
