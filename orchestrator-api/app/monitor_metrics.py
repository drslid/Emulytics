"""Read-only monitoring aggregates; historical percentiles use a bounded sample."""

from collections import Counter
from datetime import timedelta
from typing import Literal

import psycopg

from .console_routes import device_connection
from .execution_store import ACTIVE


Window = Literal["1h", "24h", "7d"]
WINDOW_SECONDS = {"1h": 3600, "24h": 86400, "7d": 604800}
SAMPLE_LIMIT = 5000
HEARTBEAT_INTERVAL_SECONDS = 5
STALE_AFTER_SECONDS = 20


def result_metrics(connection, observed_at, window):
    seconds = WINDOW_SECONDS[window]
    result = connection.execute(
        """WITH recent AS MATERIALIZED (
          SELECT id,status,created_at,started_at,finished_at FROM executions
          WHERE finished_at >= %s AND finished_at <= %s
            AND status IN ('succeeded','failed','cancelled','needs_review')
          ORDER BY finished_at DESC,id DESC LIMIT %s
        ), sample AS (
          SELECT * FROM recent ORDER BY finished_at DESC,id DESC LIMIT %s
        )
        SELECT COUNT(*) AS sample_size,
          (SELECT COUNT(*) > %s FROM recent) AS truncated,
          COUNT(*) FILTER (WHERE status='succeeded') AS succeeded,
          COUNT(*) FILTER (WHERE status='failed') AS failed,
          COUNT(*) FILTER (WHERE status='cancelled') AS cancelled,
          COUNT(*) FILTER (WHERE status='needs_review') AS needs_review,
          COUNT(*) FILTER (WHERE started_at IS NOT NULL AND finished_at>=started_at) AS duration_sample_size,
          percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM finished_at-started_at))
            FILTER (WHERE started_at IS NOT NULL AND finished_at>=started_at) AS duration_p50_seconds,
          percentile_cont(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM finished_at-started_at))
            FILTER (WHERE started_at IS NOT NULL AND finished_at>=started_at) AS duration_p95_seconds,
          COUNT(*) FILTER (WHERE started_at IS NOT NULL AND started_at>=created_at) AS queue_wait_sample_size,
          percentile_cont(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM started_at-created_at))
            FILTER (WHERE started_at IS NOT NULL AND started_at>=created_at) AS queue_wait_p95_seconds
        FROM sample""",
        (observed_at - timedelta(seconds=seconds), observed_at,
         SAMPLE_LIMIT + 1, SAMPLE_LIMIT, SAMPLE_LIMIT),
    ).fetchone()
    last_success = connection.execute(
        "SELECT finished_at FROM executions WHERE status='succeeded' AND finished_at<=%s "
        "ORDER BY finished_at DESC,id DESC LIMIT 1", (observed_at,),
    ).fetchone()
    completed = result["succeeded"] + result["failed"]
    return {**result, "window": window, "window_seconds": seconds, "sample_limit": SAMPLE_LIMIT,
            "success_percent": round(100 * result["succeeded"] / completed, 2) if completed else None,
            "last_success_at": last_success["finished_at"] if last_success else None}


def database_metrics(connection):
    try:
        # A missing statistics privilege must not abort the enclosing snapshot transaction.
        with connection.transaction():
            return connection.execute(
                "SELECT CASE WHEN pg_has_role(current_user,'pg_read_all_stats','USAGE') THEN "
                "(SELECT COUNT(*) FROM pg_stat_activity WHERE backend_type='client backend') "
                "ELSE NULL END AS connections_used,"
                "current_setting('max_connections')::integer AS connections_max,"
                "pg_database_size(current_database()) AS size_bytes"
            ).fetchone()
    except psycopg.errors.InsufficientPrivilege:
        return {}


def fleet_metrics(devices, services, observed_at, queued_by_host):
    workers = [service for service in services if service["component"] == "worker"]
    live_workers = {(worker["host_id"], worker["instance_id"]) for worker in workers
                    if worker["live"] and worker["status"] == "ready"}
    occupied_workers = set()
    active_by_worker = Counter()
    fleet = dict.fromkeys(("total", "ready", "busy", "needs_review", "connected", "unauthorized",
                           "offline", "not_connected", "unknown", "worker_offline"), 0)
    hosts = {}

    def host_row(host_id):
        if host_id not in hosts:
            hosts[host_id] = {"host_id": host_id, "devices": 0, "live_workers": 0,
                              "busy_workers": 0, "connected_devices": 0, "ready_devices": 0,
                              "queued": queued_by_host.get(host_id, 0)}
        return hosts[host_id]

    for worker in workers:
        if worker["host_id"] is not None:
            host_row(worker["host_id"])
    unconfirmed = 0
    for device in devices:
        host = host_row(device["host_id"])
        host["devices"] += 1
        fleet["total"] += 1
        state = device_connection(device, workers)["connection_status"]
        fleet[state] += 1
        connected = state == "connected"
        host["connected_devices"] += int(connected)
        owned = device["owner_id"] is not None
        expired = owned and device["expires_at"] <= observed_at
        review = bool(device["quarantined"] or expired)
        busy = bool(owned and not expired and not device["quarantined"])
        ready = bool(connected and not owned and not device["quarantined"])
        fleet["needs_review"] += int(review)
        fleet["busy"] += int(busy)
        fleet["ready"] += int(ready)
        host["ready_devices"] += int(ready)
        if busy:
            owner = (device["host_id"], device["owner_id"])
            active_by_worker[owner] += 1
            if owner in live_workers:
                occupied_workers.add(owner)
            else:
                unconfirmed += 1

    for host_id, owner_id in live_workers:
        if host_id is not None:
            host_row(host_id)["live_workers"] += 1
    for host_id, owner_id in occupied_workers:
        host_row(host_id)["busy_workers"] += 1
    for service in services:
        service["active_executions"] = active_by_worker[(service["host_id"], service["instance_id"])] \
            if service["component"] == "worker" else 0
    count, busy = len(live_workers), len(occupied_workers)
    capacity = {"live_workers": count, "busy_workers": busy, "idle_workers": count - busy,
                "utilization_percent": round(100 * busy / count, 1) if count else None,
                "unconfirmed_leases": unconfirmed}
    return fleet, sorted(hosts.values(), key=lambda row: row["host_id"]), capacity


def readings(connection, observed_at, services, window):
    states = connection.execute(
        "SELECT status,COUNT(*) AS count,MIN(created_at) AS oldest_created_at "
        "FROM executions GROUP BY status ORDER BY status"
    ).fetchall()
    queues = [{"status": row["status"], "count": row["count"]} for row in states]
    counts = {row["status"]: row["count"] for row in states}
    oldest = next((row["oldest_created_at"] for row in states if row["status"] == "queued"), None)
    queue = {"queued": counts.get("queued", 0), "oldest_created_at": oldest,
             "oldest_age_seconds": max(0, (observed_at - oldest).total_seconds()) if oldest else None,
             "active": sum(counts.get(status, 0) for status in ACTIVE),
             "waiting_auth": counts.get("waiting_auth", 0)}
    devices = connection.execute(
        "SELECT d.device_id,d.host_id,d.serial,l.owner_id,l.expires_at,"
        "COALESCE(l.quarantined,false) AS quarantined FROM devices d "
        "LEFT JOIN device_leases l USING(device_id) ORDER BY d.host_id,d.device_id"
    ).fetchall()
    queued_by_host = {row["host_id"]: row["queued"] for row in connection.execute(
        "SELECT d.host_id,COUNT(*) AS queued FROM executions e JOIN devices d USING(device_id) "
        "WHERE e.status='queued' GROUP BY d.host_id"
    ).fetchall()}
    fleet, hosts, capacity = fleet_metrics(devices, services, observed_at, queued_by_host)
    leases = {"active": sum(1 for row in devices if row["owner_id"] is not None
                            and row["expires_at"] > observed_at),
              "needs_review": fleet["needs_review"]}
    schedule = connection.execute(
        "SELECT COUNT(*) FILTER (WHERE enabled) AS enabled,"
        "MIN(next_run_at) FILTER (WHERE enabled) AS next_run_at,"
        "COUNT(*) FILTER (WHERE enabled AND next_run_at < %s) AS overdue,"
        "COUNT(*) FILTER (WHERE last_error IS NOT NULL) AS errors,"
        "MIN(next_run_at) FILTER (WHERE enabled AND next_run_at < %s) AS oldest_overdue_at "
        "FROM automation_schedules", (observed_at - timedelta(seconds=30),) * 2,
    ).fetchone()
    overdue_at = schedule.pop("oldest_overdue_at")
    return {"queues": queues, "queue": queue, "hosts": hosts, "leases": leases,
            "fleet": fleet, "capacity": capacity,
            "results": result_metrics(connection, observed_at, window),
            "schedules": {"enabled": schedule["enabled"], "next_run_at": schedule["next_run_at"]},
            "schedule_health": {"overdue": schedule["overdue"], "errors": schedule["errors"],
                                "oldest_overdue_seconds": max(0, (observed_at - overdue_at).total_seconds())
                                if overdue_at else None}}
