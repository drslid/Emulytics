"""Edit device labels and remove idle registrations while preserving their history."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field, field_validator

from .access import audit_event
from .emulator_store import EmulatorStore
from .run_models import Contract, DeviceView, Identifier
from .run_routes import ControlRoute, Store


router = APIRouter(prefix='/console/devices', tags=['Device administration'], route_class=ControlRoute)


class DeviceRename(Contract):
    display_name: str = Field(min_length=1, max_length=160)

    @field_validator('display_name', mode='before')
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


def _actor(request):
    user = getattr(request.state, 'auth_user', None)
    return UUID(str(user['id'])) if user else None


@router.patch('/{device_id}', response_model=DeviceView)
def rename_device(device_id: Identifier, payload: DeviceRename, request: Request, store: Store):
    actor = _actor(request)
    with store.connect() as connection:
        EmulatorStore._actor(connection, actor)
        updated = connection.execute(
            'UPDATE devices SET display_name=%s WHERE device_id=%s RETURNING *',
            (payload.display_name, device_id),
        ).fetchone()
        if updated is None:
            raise HTTPException(404, 'Device not found')
        audit_event(connection, actor, 'device.renamed', device_id, category='automation')
        return updated


@router.delete('/{device_id}', status_code=204)
def delete_device(device_id: Identifier, request: Request, store: Store):
    actor = _actor(request)
    with store.connect() as connection:
        EmulatorStore._actor(connection, actor)
        device = connection.execute('SELECT deleted_at FROM device_records WHERE device_id=%s FOR UPDATE', (device_id,)).fetchone()
        if device is None:
            raise HTTPException(404, 'Device not found')
        if device['deleted_at'] is not None:
            return Response(status_code=204)
        EmulatorStore._idle(connection, device_id, error_code='device_busy')
        emulator = EmulatorStore._record(connection, device_id)
        if emulator and emulator['state'] not in {'created', 'stopped'}:
            raise HTTPException(409, {'code': 'stop_emulator_first'})
        if connection.execute('SELECT 1 FROM automation_schedules WHERE enabled AND device_ids ? %s LIMIT 1',
                              (device_id,)).fetchone():
            raise HTTPException(409, {'code': 'device_scheduled'})
        groups = connection.execute('SELECT id FROM device_groups WHERE id IN '
                                    '(SELECT group_id FROM device_group_members WHERE device_id=%s) '
                                    'ORDER BY id FOR UPDATE', (device_id,)).fetchall()
        connection.execute('DELETE FROM device_group_members WHERE device_id=%s', (device_id,))
        connection.execute('UPDATE device_groups SET revision=revision+1,updated_at=clock_timestamp() WHERE id=ANY(%s)',
                           ([group['id'] for group in groups],))
        connection.execute('DELETE FROM live_screen_requests WHERE device_id=%s', (device_id,))
        retired = connection.execute('UPDATE device_records SET deleted_at=clock_timestamp() WHERE device_id=%s RETURNING deleted_at',
                                     (device_id,)).fetchone()
        connection.execute('UPDATE managed_emulator_records SET deleted_at=%s WHERE device_id=%s', (retired['deleted_at'], device_id))
        audit_event(connection, actor, 'device.removed', device_id, category='automation')
    return Response(status_code=204)
