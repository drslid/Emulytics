"""Authenticated live architecture and a deliberately secret-free event journal."""
import asyncio
import json
import os
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from .auth import AuthConfig, AuthStore, SESSION_COOKIE, auth_enabled, valid_control_token
from .run_routes import Store, Limit, Offset

router = APIRouter(prefix="/console", tags=["Monitoring"])


def snapshot(store):
    started = time.monotonic()
    with store.connect() as connection:
        connection.execute("SELECT 1")
        latency = round((time.monotonic() - started) * 1000, 1)
        services = connection.execute(
            "SELECT *, last_seen_at > clock_timestamp() - interval '20 seconds' AS live "
            "FROM service_heartbeats ORDER BY component,instance_id"
        ).fetchall()
        queues = connection.execute(
            "SELECT status,COUNT(*) AS count FROM executions GROUP BY status ORDER BY status"
        ).fetchall()
        hosts = connection.execute(
            "SELECT host_id,COUNT(*) AS devices FROM devices GROUP BY host_id ORDER BY host_id"
        ).fetchall()
        leases = connection.execute(
            "SELECT COUNT(*) FILTER (WHERE owner_id IS NOT NULL AND expires_at > clock_timestamp()) AS active, "
            "COUNT(*) FILTER (WHERE quarantined OR (owner_id IS NOT NULL AND expires_at <= clock_timestamp())) "
            "AS needs_review FROM device_leases"
        ).fetchone()
        schedules = connection.execute(
            "SELECT COUNT(*) FILTER (WHERE enabled) AS enabled,MIN(next_run_at) FILTER (WHERE enabled) AS next_run_at "
            "FROM automation_schedules"
        ).fetchone()
    # This address is deployment-owned, never accepted from query parameters.
    ui_url = os.getenv("EMULYTIX_UI_INTERNAL_URL", "")
    ui_status = "unconfigured"
    if ui_url:
        try:
            result = httpx.get(ui_url, timeout=2, follow_redirects=False)
            ui_status = "ready" if result.status_code < 400 else "unavailable"
        except httpx.HTTPError:
            ui_status = "unavailable"
    for component in ("api", "scheduler", "worker"):
        if not any(row["component"] == component for row in services):
            services.append({"component": component, "instance_id": component, "host_id": None,
                             "status": "missing", "live": False, "metrics": {}, "last_seen_at": None})
    return {"observed_at": datetime.now(timezone.utc), "database": {"status": "ready", "latency_ms": latency},
            "web": {"status": ui_status}, "services": services, "queues": queues, "hosts": hosts,
            "leases": leases, "schedules": schedules}


@router.get("/monitor")
def monitor(store: Store):
    return snapshot(store)


@router.get("/monitor/stream")
async def monitor_stream(request: Request, store: Store):
    service_token = valid_control_token(request)
    config = AuthConfig.load() if auth_enabled() and not service_token else None
    token = request.cookies.get(SESSION_COOKIE)
    async def events():
        while not await request.is_disconnected():
            try:
                if config:
                    user = await run_in_threadpool(AuthStore(config).current_user, token)
                    if not user or "monitor.read" not in user.get("permissions", []):
                        yield 'event: revoked\ndata: {}\n\n'
                        return
                data = await run_in_threadpool(snapshot, store)
                yield 'data: ' + json.dumps(jsonable_encoder(data), ensure_ascii=False) + '\n\n'
            except Exception:
                # Never send exception text, database URLs or stale success over this channel.
                yield 'event: unavailable\ndata: {}\n\n'
            await asyncio.sleep(2)
    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "private, no-store", "X-Accel-Buffering": "no"})


@router.get("/logs")
def logs(store: Store, limit: Limit = 50, offset: Offset = 0,
         q: str = Query(default="", max_length=128), category: str = Query(default="", max_length=32),
         severity: str = Query(default="", max_length=16)):
    # Only allowlisted correlation fields are exposed; arbitrary event payloads are excluded.
    journal = """SELECT 'audit-' || a.id AS id,a.occurred_at AS occurred_at,a.severity,a.category,a.action,
        a.entity_id,u.username AS actor FROM audit_log a LEFT JOIN auth_users u ON u.id=a.actor_id
        UNION ALL
        SELECT 'run-' || e.run_id || '-' || e.sequence,e.created_at,
        CASE WHEN e.type LIKE '%%failed%%' OR e.payload->>'status' = 'failed' THEN 'error' WHEN e.type LIKE '%%review%%' OR e.payload->>'status' = 'needs_review' THEN 'warning' ELSE 'info' END,
        'execution',e.type,e.run_id::text,NULL FROM run_events e"""
    conditions = "WHERE (%s = '' OR action ILIKE %s OR entity_id ILIKE %s OR actor ILIKE %s) " \
                 "AND (%s = '' OR category = %s) AND (%s = '' OR severity = %s)"
    params = (q, f"%{q}%", f"%{q}%", f"%{q}%", category, category, severity, severity)
    with store.connect() as connection:
        total = connection.execute(f"WITH journal AS ({journal}) SELECT COUNT(*) AS total FROM journal {conditions}", params).fetchone()["total"]
        items = connection.execute(f"WITH journal AS ({journal}) SELECT * FROM journal {conditions} "
                                   "ORDER BY occurred_at DESC,id DESC LIMIT %s OFFSET %s", (*params, limit, offset)).fetchall()
    return {"items": items, "total": total, "limit": limit, "offset": offset}
