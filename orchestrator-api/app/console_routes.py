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
            "(SELECT COUNT(*) FROM workflows WHERE deleted_at IS NULL AND workflow_id NOT LIKE 'emulator-system-%%') AS workflows_total, "
            "COUNT(*) AS runs_total, "
            "COUNT(*) FILTER (WHERE status IN ('queued', 'running')) AS runs_active, "
            "COUNT(*) FILTER (WHERE status = 'needs_review') AS runs_needs_review, "
            "COUNT(*) FILTER (WHERE status = 'succeeded') AS runs_succeeded FROM runs"
        ).fetchone()


def device_connection(device: dict, workers: list[dict]) -> dict:
    matching = [worker for worker in workers if worker["host_id"] == device["host_id"]]
    live = [worker for worker in matching if worker["live"] and worker["status"] == "ready"]
    last_seen = matching[0]["last_seen_at"] if matching else None
    state = "worker_offline" if not live else "unknown"
    observed = []
    for worker in live:
        metrics = worker["metrics"]
        if not isinstance(metrics, dict) or metrics.get("adb_status") != "ready":
            continue
        if not isinstance(metrics.get("devices"), list):
            continue
        state = "not_connected"
        observed.extend(entry.get("state") for entry in metrics["devices"]
                        if isinstance(entry, dict) and entry.get("serial") == device["serial"])
    if "device" in observed:
        state = "connected"
    elif "unauthorized" in observed:
        state = "unauthorized"
    elif any(value in {"offline", "recovery", "sideload", "bootloader"} for value in observed if isinstance(value, str)):
        state = "offline"
    return {"connection_status": state, "worker_last_seen_at": last_seen}


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
        workers = connection.execute(
            "SELECT host_id,status,metrics,last_seen_at, "
            "last_seen_at > clock_timestamp() - interval '20 seconds' AS live "
            "FROM service_heartbeats WHERE component='worker' ORDER BY last_seen_at DESC",
        ).fetchall()
        worker_hosts = sorted({worker["host_id"] for worker in workers
                               if worker["live"] and worker["status"] == "ready" and worker["host_id"]})
        return {"items": [{**item, **device_connection(item, workers)} for item in items],
                "total": total, "limit": limit, "offset": offset, "worker_hosts": worker_hosts}


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
