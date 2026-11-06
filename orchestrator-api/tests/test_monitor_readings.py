"""Monitoring observations use only the disposable PostgreSQL fixture."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

from app.telemetry import heartbeat


def test_empty_readings_preserve_unknowns_and_default_window(control_client):
    response = control_client.get("/console/monitor")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["freshness"] == {"heartbeat_interval_seconds": 5, "stale_after_seconds": 20}
    assert data["capacity"] == {
        "live_workers": 0, "busy_workers": 0, "idle_workers": 0,
        "utilization_percent": None, "unconfirmed_leases": 0,
    }
    assert data["queue"] == {
        "queued": 0, "oldest_created_at": None, "oldest_age_seconds": None,
        "active": 0, "waiting_auth": 0,
    }
    results = data["results"]
    assert results["window"] == "24h"
    assert results["window_seconds"] == 86400
    assert results["sample_size"] == 0
    assert results["sample_limit"] == 5000
    assert results["truncated"] is False
    for field in ("success_percent", "duration_p50_seconds", "duration_p95_seconds",
                  "queue_wait_p95_seconds", "last_success_at"):
        assert results[field] is None
    assert results["duration_sample_size"] == results["queue_wait_sample_size"] == 0
    assert data["schedules"] == {"enabled": 0, "next_run_at": None}
    assert data["schedule_health"]["overdue"] == 0
    assert data["schedule_health"]["oldest_overdue_seconds"] is None
    for service in data["services"]:
        assert service["age_seconds"] is None
        assert service["active_executions"] == 0


def insert_execution(connection, run_id, device_id, attempt, status, created_at,
                     started_at=None, finished_at=None):
    execution_id = uuid4()
    connection.execute(
        "INSERT INTO executions(id,run_id,device_id,attempt,status,created_at,started_at,finished_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
        (execution_id, run_id, device_id, attempt, status, created_at, started_at, finished_at),
    )
    return execution_id


def test_result_windows_use_finished_observations_and_explicit_denominators(
        registered, database_dsn, run_payload):
    run = registered.post("/runs", json=run_payload).json()
    now = datetime.now(timezone.utc)
    finished = now - timedelta(minutes=10)
    with psycopg.connect(database_dsn) as connection:
        connection.execute(
            "UPDATE executions SET created_at=%s WHERE run_id=%s",
            (now - timedelta(seconds=120), run["id"]),
        )
        insert_execution(connection, run["id"], "phone-1", 2, "succeeded",
                         finished - timedelta(seconds=120),
                         finished - timedelta(seconds=100), finished)
        insert_execution(connection, run["id"], "phone-1", 3, "failed",
                         finished - timedelta(seconds=30),
                         finished - timedelta(seconds=20), finished)
        insert_execution(connection, run["id"], "phone-1", 4, "cancelled",
                         finished - timedelta(seconds=30), finished_at=finished)
        insert_execution(connection, run["id"], "phone-1", 5, "needs_review",
                         finished - timedelta(seconds=30), finished_at=finished)
        older = now - timedelta(hours=2)
        insert_execution(connection, run["id"], "phone-1", 6, "failed",
                         older - timedelta(seconds=50), older - timedelta(seconds=40), older)
    response = registered.get("/console/monitor", params={"window": "1h"})
    assert response.status_code == 200, response.text
    data = response.json()
    results = data["results"]
    assert results["window"] == "1h"
    assert results["window_seconds"] == 3600
    assert results["sample_size"] == 4
    assert results["truncated"] is False
    assert {key: results[key] for key in ("succeeded", "failed", "cancelled", "needs_review")} == {
        "succeeded": 1, "failed": 1, "cancelled": 1, "needs_review": 1,
    }
    assert results["success_percent"] == 50
    assert results["duration_sample_size"] == 2
    assert results["queue_wait_sample_size"] == 2
    assert results["duration_p50_seconds"] == pytest.approx(60)
    assert results["duration_p95_seconds"] == pytest.approx(96)
    assert results["queue_wait_p95_seconds"] == pytest.approx(19.5)
    assert datetime.fromisoformat(results["last_success_at"]) == finished
    assert data["queue"]["queued"] == 1
    assert 120 <= data["queue"]["oldest_age_seconds"] < 180
    day = registered.get("/console/monitor", params={"window": "24h"}).json()["results"]
    assert day["sample_size"] == 5
    assert day["failed"] == 2
    assert day["success_percent"] == pytest.approx(100 / 3, abs=0.01)
    week = registered.get("/console/monitor", params={"window": "7d"}).json()["results"]
    assert week["window_seconds"] == 604800
    assert week["sample_size"] == 5


@pytest.mark.parametrize("path", ["/console/monitor", "/console/monitor/stream"])
@pytest.mark.parametrize("window", ["30d", "", "1h' OR 1=1 --"])
def test_monitor_rejects_unknown_windows_before_opening_stream(control_client, path, window):
    assert control_client.get(path, params={"window": window}).status_code == 422


def test_worker_capacity_and_fleet_deduplicate_fresh_adb_observations(
        registered, database_dsn, run_payload):
    for device_id, host_id, serial in (
        ("phone-2", "host-1", "Serial2"),
        ("phone-3", "host-2", "Serial3"),
        ("phone-4", "host-1", "Serial4"),
    ):
        response = registered.post("/devices", json={
            "device_id": device_id, "host_id": host_id, "serial": serial, "kind": "physical",
        })
        assert response.status_code == 201, response.text
    run = registered.post("/runs", json=run_payload).json()
    now = datetime.now(timezone.utc)
    with psycopg.connect(database_dsn) as connection:
        first_id = connection.execute(
            "UPDATE executions SET status='running',started_at=%s WHERE run_id=%s RETURNING id",
            (now - timedelta(seconds=10), run["id"]),
        ).fetchone()[0]
        second_id = insert_execution(connection, run["id"], "phone-2", 1, "waiting_auth", now)
        insert_execution(connection, run["id"], "phone-3", 1, "queued", now)
        insert_execution(connection, run["id"], "phone-4", 1, "queued", now)
        for device_id, owner, execution_id in (
            ("phone-1", "worker-busy", first_id),
            ("phone-2", "worker-stale", second_id),
        ):
            connection.execute(
                "INSERT INTO device_leases(device_id,owner_id,execution_id,expires_at) "
                "VALUES(%s,%s,%s,%s)",
                (device_id, owner, execution_id, now + timedelta(minutes=5)),
            )
    observations = {"adb_status": "ready", "devices": [
        {"serial": "emulator-5554", "state": "device"},
        {"serial": "Serial2", "state": "device"},
        {"serial": "Serial4", "state": "device"},
        {"serial": "unregistered", "state": "device"},
    ]}
    heartbeat(database_dsn, "worker", "worker-busy", "host-1", metrics=observations)
    heartbeat(database_dsn, "worker", "worker-idle", "host-1", metrics=observations)
    heartbeat(database_dsn, "worker", "worker-stale", "host-1", metrics=observations)
    heartbeat(database_dsn, "worker", "host-2-stale", "host-2", metrics={
        "adb_status": "ready", "devices": [{"serial": "Serial3", "state": "device"}],
    })
    with psycopg.connect(database_dsn) as connection:
        connection.execute(
            "UPDATE service_heartbeats SET last_seen_at=%s "
            "WHERE instance_id IN ('worker-stale','host-2-stale')",
            (now - timedelta(seconds=60),),
        )
    response = registered.get("/console/monitor")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["capacity"] == {
        "live_workers": 2, "busy_workers": 1, "idle_workers": 1,
        "utilization_percent": 50, "unconfirmed_leases": 1,
    }
    assert data["fleet"]["total"] == 4
    assert data["fleet"]["connected"] == 3
    assert data["fleet"]["worker_offline"] == 1
    assert data["fleet"]["ready"] == 1
    assert data["fleet"]["busy"] == 2
    assert data["fleet"]["needs_review"] == 0
    assert data["queue"]["active"] == 2
    assert data["queue"]["waiting_auth"] == 1
    hosts = {host["host_id"]: host for host in data["hosts"]}
    assert hosts["host-1"]["devices"] == 3
    assert hosts["host-1"]["connected_devices"] == 3
    assert hosts["host-1"]["ready_devices"] == 1
    assert hosts["host-1"]["live_workers"] == 2
    assert hosts["host-1"]["busy_workers"] == 1
    assert hosts["host-1"]["queued"] == 1
    assert hosts["host-2"]["connected_devices"] == 0
    assert hosts["host-2"]["queued"] == 1
    services = {service["instance_id"]: service for service in data["services"]}
    assert services["worker-busy"]["active_executions"] == 1
    assert services["worker-idle"]["active_executions"] == 0
    assert services["worker-stale"]["age_seconds"] >= 60
    assert services["worker-stale"]["live"] is False


def test_result_cap_is_declared_and_last_success_is_global(
        registered, database_dsn, run_payload):
    run = registered.post("/runs", json=run_payload).json()
    with psycopg.connect(database_dsn) as connection:
        connection.execute(
            "INSERT INTO executions(id,run_id,device_id,attempt,status,created_at,started_at,finished_at) "
            "SELECT gen_random_uuid(),%s,'phone-1',n+1, "
            "CASE WHEN n=5001 THEN 'succeeded' ELSE 'failed' END, "
            "clock_timestamp()-interval '3 hours',clock_timestamp()-interval '2 hours', "
            "clock_timestamp()-n*interval '1 second' FROM generate_series(1,5001) AS n",
            (run["id"],),
        )
    results = registered.get("/console/monitor").json()["results"]
    assert results["sample_size"] == results["sample_limit"] == 5000
    assert results["truncated"] is True
    assert results["failed"] == 5000
    assert results["succeeded"] == 0
    assert results["success_percent"] == 0
    assert results["last_success_at"] is not None
    hour = registered.get("/console/monitor", params={"window": "1h"}).json()["results"]
    assert hour["truncated"] is False
    assert 3500 < hour["sample_size"] < 3650
    assert hour["last_success_at"] == results["last_success_at"]


def test_schedule_health_applies_grace_and_excludes_disabled_schedules(
        registered, database_dsn):
    now = datetime.now(timezone.utc)
    with psycopg.connect(database_dsn) as connection:
        for name, delay, enabled, error in (
            ("delayed", 120, True, "dispatch_failed"),
            ("within-grace", 10, True, None),
            ("disabled", 600, False, None),
        ):
            connection.execute(
                "INSERT INTO automation_schedules(id,name,workflow_id,workflow_version,device_ids, "
                "max_concurrency,cron,timezone,enabled,next_run_at,last_error) "
                "VALUES(%s,%s,'go-home',1,'[\"phone-1\"]',1,'* * * * *','UTC',%s,%s,%s)",
                (uuid4(), name, enabled, now - timedelta(seconds=delay), error),
            )
    data = registered.get("/console/monitor").json()
    assert data["schedules"]["enabled"] == 2
    assert data["schedule_health"]["overdue"] == 1
    assert data["schedule_health"]["errors"] == 1
    assert 120 <= data["schedule_health"]["oldest_overdue_seconds"] < 180
