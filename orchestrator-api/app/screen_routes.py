"""Private on-demand display frames; Android access stays in the device worker."""
import os
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from .execution_store import ACTIVE
from .live_screen import MAX_FRAME_AGE, ScreenUnavailable, read_frame
from .run_models import Identifier
from .run_routes import ControlRoute, Store

router = APIRouter(prefix="/console", tags=["Live Android display"], route_class=ControlRoute)


@router.get("/devices/{device_id}/screen")
def screen(device_id: Identifier, store: Store):
    with store.connect() as connection:
        if not connection.execute("SELECT 1 FROM devices WHERE device_id=%s", (device_id,)).fetchone():
            raise HTTPException(404, "Device not found")
        connection.execute(
            "INSERT INTO live_screen_requests(device_id,expires_at) VALUES(%s,clock_timestamp()+interval '15 seconds') "
            "ON CONFLICT(device_id) DO UPDATE SET expires_at=EXCLUDED.expires_at "
            "WHERE live_screen_requests.expires_at<clock_timestamp()+interval '8 seconds'",
            (device_id,),
        )
    root = os.getenv("EMULYTIX_ARTIFACT_ROOT", "")
    if not root:
        raise HTTPException(503, "Live screen unavailable")
    try:
        image, metadata, age = read_frame(root, device_id)
    except (OSError, ScreenUnavailable):
        raise HTTPException(503, "Live screen warming or unavailable") from None
    return Response(image, media_type="image/png", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "X-Screen-Captured-At": metadata["captured_at"], "X-Screen-Age": f"{age:.3f}",
        "X-Screen-Frame-Id": metadata["frame_id"],
    })


def _active_execution(connection, execution_id: UUID) -> dict:
    initial = connection.execute('SELECT run_id FROM executions WHERE id=%s', (execution_id,)).fetchone()
    if initial is None:
        raise HTTPException(404, 'Execution not found')
    # Match runtime lock order: a writer always takes the run before the device lease.
    connection.execute('SELECT id FROM runs WHERE id=%s FOR SHARE', (initial['run_id'],)).fetchone()
    execution = connection.execute(
        'SELECT device_id,status,started_at,lease_epoch FROM executions WHERE id=%s', (execution_id,),
    ).fetchone()
    if execution is None or execution['status'] not in ACTIVE:
        raise HTTPException(410, 'Execution display has ended')
    lease = connection.execute(
        'SELECT owner_id,execution_id,lease_epoch,expires_at,quarantined FROM device_leases '
        'WHERE device_id=%s FOR SHARE', (execution['device_id'],),
    ).fetchone()
    if (lease is None or lease['owner_id'] is None or lease['quarantined']
            or lease['execution_id'] != execution_id or lease['lease_epoch'] != execution['lease_epoch']
            or not connection.execute('SELECT %s>clock_timestamp() AS live', (lease['expires_at'],)).fetchone()['live']):
        raise HTTPException(410, 'Execution display has ended')
    if execution['started_at'] is None:
        raise HTTPException(503, 'Execution display is preparing')
    return {**execution, 'owner_id': lease['owner_id'], 'expires_at': lease['expires_at']}


@router.get('/executions/{execution_id}/screen')
def execution_screen(execution_id: UUID, store: Store):
    with store.connect() as connection:
        before = _active_execution(connection, execution_id)
    root = os.getenv('EMULYTIX_ARTIFACT_ROOT', '')
    if not root:
        raise HTTPException(503, 'Live screen unavailable')
    frame = None
    try:
        frame = read_frame(root, before['device_id'])
    except (OSError, ScreenUnavailable):
        pass
    response = None
    with store.connect() as connection:
        current = _active_execution(connection, execution_id)
        if any(current[key] != before[key] for key in ('device_id', 'lease_epoch', 'owner_id', 'started_at')):
            raise HTTPException(410, 'Execution display has ended')
        connection.execute(
            "INSERT INTO live_screen_requests(device_id,expires_at) VALUES(%s,clock_timestamp()+interval '15 seconds') "
            'ON CONFLICT(device_id) DO UPDATE SET expires_at=EXCLUDED.expires_at '
            "WHERE live_screen_requests.expires_at<clock_timestamp()+interval '8 seconds'", (current['device_id'],),
        )
        if frame is not None:
            image, metadata, _ = frame
            captured_at = datetime.fromisoformat(metadata['captured_at'])
            age = (datetime.now(timezone.utc)-captured_at).total_seconds()
            if captured_at < current['started_at'] or not -1 <= age <= MAX_FRAME_AGE:
                frame = None
        if not connection.execute('SELECT %s>clock_timestamp() AS live', (current['expires_at'],)).fetchone()['live']:
            raise HTTPException(410, 'Execution display has ended')
        if frame is not None:
            response = Response(image, media_type='image/png', headers={
                'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
                'X-Screen-Captured-At': metadata['captured_at'], 'X-Screen-Age': f'{max(0.0, age):.3f}',
                'X-Screen-Frame-Id': metadata['frame_id'],
            })
    # A warming response still commits the request, so the worker can produce its first new frame.
    if response is None:
        raise HTTPException(503, 'Live screen warming or unavailable')
    return response
