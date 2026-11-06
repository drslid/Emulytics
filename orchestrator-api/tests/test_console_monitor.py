import asyncio
from datetime import datetime, timezone

import httpx
import psycopg
from psycopg.types.json import Jsonb
from starlette.requests import Request

from app.auth import AuthStore
from app import monitor_routes
from app.monitor_routes import monitor_stream, snapshot
from app.run_models import DeviceRegistration
from app.run_store import RunStore
from app.telemetry import heartbeat
from test_authentication import auth_store, auth_client, create_enabled, current_code, PASSWORD


def test_live_architecture_reports_observed_heartbeats_and_staleness(control_client, database_dsn, monkeypatch):
    monkeypatch.delenv("EMULYTIX_UI_INTERNAL_URL", raising=False)
    heartbeat(database_dsn, "api", "api-test")
    heartbeat(database_dsn, "scheduler", "scheduler-test", status="ready", metrics={"ticks": 3})
    response = control_client.get("/console/monitor")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["database"]["status"] == "ready"
    assert data["database"]["latency_ms"] >= 0
    assert data["web"]["status"] == "unconfigured"
    services = {row["component"]: row for row in data["services"]}
    assert services["api"]["live"] is True
    assert services["scheduler"]["metrics"] == {"ticks": 3}
    assert services["worker"]["live"] is False
    assert services["worker"]["status"] == "missing"
    assert data["queues"] == []
    assert data["schedules"] == {"enabled": 0, "next_run_at": None}
    with psycopg.connect(database_dsn) as connection:
        connection.execute("UPDATE service_heartbeats SET last_seen_at=clock_timestamp()-interval '21 seconds' WHERE component='api'")
    data = control_client.get("/console/monitor").json()
    assert next(row for row in data["services"] if row["component"] == "api")["live"] is False
    heartbeat(database_dsn, "api", "api-test")
    data = control_client.get("/console/monitor").json()
    assert len([row for row in data["services"] if row["component"] == "api"]) == 1
    assert next(row for row in data["services"] if row["component"] == "api")["live"] is True


def test_monitor_web_probe_distinguishes_ready_and_failed(database_dsn, monkeypatch):
    monkeypatch.setenv("EMULYTIX_UI_INTERNAL_URL", "http://internal-console:3000")
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: httpx.Response(302))
    assert snapshot(RunStore(database_dsn))["web"]["status"] == "ready"
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: httpx.Response(500))
    assert snapshot(RunStore(database_dsn))["web"]["status"] == "unavailable"
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("private internal URL must not be shown")
    monkeypatch.setattr(httpx, "get", unavailable)
    assert snapshot(RunStore(database_dsn))["web"]["status"] == "unavailable"


def test_journal_is_paginated_filtered_and_excludes_event_payloads(registered, database_dsn, run_payload):
    run = registered.post("/runs", json=run_payload).json()
    sentinel = "SENSITIVE-DEVICE-TEXT-AND-PASSWORD"
    with psycopg.connect(database_dsn) as connection:
        connection.execute("INSERT INTO audit_log(action,entity_id,severity,category,metadata) VALUES('user.test','account-1','warning','security',%s)", (Jsonb({"unreviewed": sentinel}),))
        connection.execute("INSERT INTO run_events(run_id,sequence,type,payload) VALUES(%s,2,'step.failed',%s)", (run["id"], Jsonb({"error": sentinel, "arguments": {"password": sentinel}})))
    response = registered.get("/console/logs", params={"limit": 1})
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 1
    assert response.json()["total"] >= 3
    assert sentinel not in response.text
    response = registered.get("/console/logs", params={"category": "execution", "severity": "error", "q": "step.failed"})
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["entity_id"] == run["id"]
    assert set(response.json()["items"][0]) == {"id", "occurred_at", "severity", "category", "action", "entity_id", "actor"}
    assert sentinel not in response.text
    assert registered.get("/console/logs", params={"q": "' OR 1=1; --"}).json()["total"] == 0


def test_viewer_monitors_but_only_auditor_can_read_journal(auth_client, auth_store):
    user, secret = create_enabled(auth_store, "monitor-viewer")
    with auth_store.connect() as connection:
        connection.execute("UPDATE auth_users SET role='viewer' WHERE id=%s", (user["id"],))
    auth_client.post("/auth/login", json={"username": "monitor-viewer", "password": PASSWORD})
    assert auth_client.post("/auth/verify", json={"code": current_code(auth_store, secret)}).status_code == 200
    assert auth_client.get("/console/monitor").status_code == 200
    assert auth_client.get("/console/logs").status_code == 403
    with auth_store.connect() as connection:
        connection.execute("UPDATE auth_users SET role='auditor' WHERE id=%s", (user["id"],))
    assert auth_client.get("/console/logs").status_code == 200
    assert auth_client.post("/devices", json={"device_id": "no-permission", "host_id": "host", "serial": "ABC", "kind": "physical"}).status_code == 403


def test_sse_stops_when_session_is_revoked(auth_store, database_dsn, monkeypatch):
    async def disconnected():
        return {"type": "http.request"}
    request = Request({"type": "http", "method": "GET", "path": "/console/monitor/stream", "headers": [(b"cookie", b"emulytix_session=revoked")], "query_string": b""}, receive=disconnected)
    monkeypatch.setattr(AuthStore, "current_user", lambda *args: None)
    async def check():
        response = await monitor_stream(request, RunStore(database_dsn))
        first = await anext(response.body_iterator)
        assert first == 'event: revoked\ndata: {}\n\n'
        try:
            await anext(response.body_iterator)
        except StopAsyncIteration:
            pass
        else:
            raise AssertionError("A revoked stream must end")
    asyncio.run(check())


def test_open_sse_revalidates_permissions_before_each_snapshot(auth_store, database_dsn, monkeypatch):
    async def receive():
        return {"type": "http.request"}
    async def no_wait(_):
        pass
    request = Request({"type": "http", "method": "GET", "path": "/console/monitor/stream", "headers": [(b"cookie", b"emulytix_session=initially-valid")], "query_string": b""}, receive=receive)
    users = iter([{"permissions": ["monitor.read"]}, {"permissions": []}])
    monkeypatch.setattr(AuthStore, "current_user", lambda *args: next(users))
    monkeypatch.setattr(monitor_routes, "snapshot", lambda store: {"observed": "once"})
    monkeypatch.setattr(monitor_routes.asyncio, "sleep", no_wait)
    async def check():
        response = await monitor_stream(request, RunStore(database_dsn))
        assert response.headers["cache-control"] == "private, no-store"
        assert await anext(response.body_iterator) == 'data: {"observed": "once"}\n\n'
        assert await anext(response.body_iterator) == 'event: revoked\ndata: {}\n\n'
        try:
            await anext(response.body_iterator)
        except StopAsyncIteration:
            pass
        else:
            raise AssertionError("Lost permissions must stop an existing stream")
    asyncio.run(check())


def test_device_names_accept_unicode_and_trim_adb_without_changing_case(control_client):
    result = control_client.post("/devices", json={"device_id": "  Téléphone de Paris  ", "host_id": " worker-Paris ", "serial": " aBc123XyZ ", "kind": "physical"})
    assert result.status_code == 201, result.text
    assert result.json()["device_id"] == "telephone-de-paris"
    assert result.json()["display_name"] == "Téléphone de Paris"
    assert result.json()["serial"] == "aBc123XyZ"
    assert result.json()["host_id"] == "worker-Paris"
    result = control_client.post("/devices", json={"device_id": "  我的手机  ", "host_id": "host", "serial": "ChinesePhone", "kind": "physical"})
    assert result.status_code == 201, result.text
    assert result.json()["device_id"].startswith("device-")
    assert result.json()["display_name"] == "我的手机"


def test_friendly_names_normalize_punctuation_and_display_whitespace(control_client):
    result = control_client.post("/devices", json={"device_id": " . Téléphone d'Alice ", "display_name": " . Téléphone d'Alice  ", "host_id": "host", "serial": "AlicePhone", "kind": "physical"})
    assert result.status_code == 201, result.text
    assert result.json()["device_id"] == "telephone-d-alice"
    assert result.json()["display_name"] == ". Téléphone d'Alice"
