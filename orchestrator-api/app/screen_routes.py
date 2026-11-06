"""Private on-demand display frames; Android access stays in the device worker."""
import os

from fastapi import APIRouter, HTTPException, Response

from .live_screen import ScreenUnavailable, read_frame
from .run_models import Identifier
from .run_routes import ControlRoute, Store

router = APIRouter(prefix="/console/devices", tags=["Live Android display"], route_class=ControlRoute)


@router.get("/{device_id}/screen")
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
