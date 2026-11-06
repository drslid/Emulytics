"""Authenticated fleet views; a registration is never proof of a live device."""

import hashlib
import os
import re
from pathlib import Path as FilePath
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from .run_models import Identifier
from .run_routes import Limit, Offset, Store


router = APIRouter(prefix="/console", tags=["Operator console"])


@router.get("/summary")
def summary(store: Store) -> dict:
    with store.connect() as connection:
        return connection.execute(
            "SELECT (SELECT COUNT(*) FROM devices) AS devices_total, "
            "(SELECT COUNT(*) FROM workflows) AS workflows_total, "
            "COUNT(*) AS runs_total, "
            "COUNT(*) FILTER (WHERE status IN ('queued', 'running')) AS runs_active, "
            "COUNT(*) FILTER (WHERE status = 'needs_review') AS runs_needs_review, "
            "COUNT(*) FILTER (WHERE status = 'succeeded') AS runs_succeeded FROM runs"
        ).fetchone()


@router.get("/fleet")
def fleet(store: Store, limit: Limit = 100, offset: Offset = 0) -> dict:
    with store.connect() as connection:
        total = connection.execute("SELECT COUNT(*) AS total FROM devices").fetchone()["total"]
        items = connection.execute(
            "SELECT d.*, CASE WHEN l.quarantined OR (l.owner_id IS NOT NULL AND l.expires_at <= clock_timestamp()) "
            "THEN 'needs_review' WHEN l.owner_id IS NOT NULL THEN 'busy' ELSE 'declared' END AS availability, "
            "e.run_id AS active_run_id, l.expires_at AS lease_expires_at "
            "FROM devices d LEFT JOIN device_leases l ON l.device_id = d.device_id "
            "LEFT JOIN executions e ON e.id = l.execution_id "
            "ORDER BY d.device_id LIMIT %s OFFSET %s", (limit, offset),
        ).fetchall()
        return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/executions/{execution_id}/captures/{step_id}")
def capture(execution_id: UUID, step_id: Identifier, store: Store) -> Response:
    root = os.getenv("EMULYTIX_ARTIFACT_ROOT", "")
    if not root:
        raise HTTPException(503, "Capture storage unavailable")
    with store.connect() as connection:
        record = connection.execute(
            "SELECT lease_epoch, evidence FROM executions WHERE id = %s", (execution_id,)
        ).fetchone()
        if record is None:
            raise HTTPException(404, "Execution not found")
    step = next((step for step in record["evidence"].get("steps", []) if step.get("step_id") == step_id), None)
    if not step or not record["lease_epoch"]:
        raise HTTPException(404, "Capture not found")
    # The DB proves the step belongs to the execution; paths supplied in JSON are not file authority.
    try:
        archive = FilePath(root).resolve(strict=True)
        execution = (archive / str(execution_id) / str(record["lease_epoch"])).resolve(strict=True)
        if execution.parent.parent != archive:
            raise ValueError("Invalid execution path")
        name = FilePath(step.get("screenshot", "")).name
        if not re.fullmatch(r"[a-f0-9]{32}\.png", name):
            raise ValueError("Invalid capture name")
        image = (execution / name).resolve(strict=True)
        if image.parent != execution:
            raise ValueError("Invalid capture path")
        data = image.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or hashlib.sha256(data).hexdigest() != step.get("screenshot_sha256"):
            raise ValueError("Capture checksum mismatch")
    except (OSError, ValueError):
        raise HTTPException(404, "Capture unavailable") from None
    return Response(data, media_type="image/png", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
