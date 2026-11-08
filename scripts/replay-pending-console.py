#!/usr/bin/env python3
"""Replay the four known local WF01 requests on a connected device; default is dry-run.

Run inside console-api, for example:
  docker compose ... exec -T console-api python - --apply < scripts/replay-pending-console.py
Original run identities, device lists, workflow versions and parameters are retained.
"""

import argparse
import json
import os
from uuid import UUID

import psycopg
from fastapi import HTTPException

from app.access import audit_event
from app.console_routes import device_connection
from app.execution_store import ExecutionStore
from app.run_models import RunSubmission
from app.run_store import RunStore

SOURCE_RUNS = (
    UUID("d463c500-b35a-4e0a-b397-5c9dbc5ef08d"),
    UUID("38d439bc-8156-4970-978e-1e8a92ab4eac"),
    UUID("667759b7-e6f2-446f-bed1-56ae6e65fc96"),
    UUID("76a3f434-9711-4f88-9e48-84453316df31"),
)


def connected_target(connection, target_id):
    target = connection.execute("SELECT * FROM devices WHERE device_id=%s", (target_id,)).fetchone()
    if not target:
        raise ValueError("Target device is not registered")
    workers = connection.execute(
        "SELECT *,last_seen_at > clock_timestamp()-interval '20 seconds' AS live "
        "FROM service_heartbeats WHERE component='worker' AND host_id=%s ORDER BY last_seen_at DESC",
        (target["host_id"],),
    ).fetchall()
    lease = connection.execute(
        "SELECT quarantined,owner_id,expires_at > clock_timestamp() AS live FROM device_leases WHERE device_id=%s",
        (target_id,),
    ).fetchone()
    if device_connection(target, workers)["connection_status"] != "connected":
        raise ValueError("Target device has no fresh confirmed Android connection")
    if lease and (lease["quarantined"] or (lease["owner_id"] and not lease["live"])):
        raise ValueError("Target device requires lease review")
    return target


def replay_one(store, source_id, target_id="local-emulator", *, apply=False, after_submission=None):
    key = f"retry:{source_id}:{target_id}"
    with store.connect() as connection:
        source = connection.execute("SELECT * FROM runs WHERE id=%s FOR UPDATE", (source_id,)).fetchone()
        if not source:
            raise ValueError(f"Source run is not present: {source_id}")
        if source["workflow_id"] != "chrome-wikipedia-football" or source["device_ids"] != ["banc-de-test"]:
            raise ValueError("Source does not match the authorized local WF01 backlog")
        if source["max_concurrency"] != 1:
            raise ValueError("Source concurrency differs from the known single-device request")
        source_device = connection.execute(
            "SELECT host_id,serial FROM devices WHERE device_id='banc-de-test'"
        ).fetchone()
        if not source_device or source_device != {"host_id": "bench", "serial": "moultiplate"}:
            raise ValueError("The original device configuration has changed; no replay performed")
        previous = connection.execute("SELECT id FROM runs WHERE idempotency_key=%s", (key,)).fetchone()
        summary = {"source_run_id": str(source_id), "target_device_id": target_id}
        if source["status"] != "queued" or source["cancel_requested"]:
            return {**summary, "status": "already_replayed" if previous else "skipped",
                    "run_id": str(previous["id"]) if previous else None,
                    "source_status": source["status"]}
        executions = connection.execute("SELECT status FROM executions WHERE run_id=%s", (source_id,)).fetchall()
        if not executions or any(row["status"] != "queued" for row in executions):
            raise ValueError("Source run has already been claimed; no replay performed")
        connected_target(connection, target_id)
        if not apply:
            return {**summary, "status": "dry_run", "run_id": str(previous["id"]) if previous else None}
        submission = RunSubmission(
            workflow_id=source["workflow_id"], workflow_version=source["workflow_version"],
            device_ids=[target_id], max_concurrency=1, parameters=source["parameters"], idempotency_key=key,
        )
        # New-run commit precedes source cancellation. The stable key repairs a crash between them.
        # This administrator-only repair owns its reserved key and its separate commit.
        with store.connect() as replacement_connection:
            replacement = store._submit_run(replacement_connection, submission)
        if after_submission:
            after_submission(replacement)
        connection.execute("SELECT id FROM runs WHERE id=%s FOR UPDATE", (replacement["id"],)).fetchone()
        connection.execute(
            "UPDATE runs SET status='cancelled',cancel_requested=true,updated_at=clock_timestamp() WHERE id=%s",
            (source_id,),
        )
        connection.execute(
            "UPDATE executions SET status='cancelled',finished_at=clock_timestamp(),updated_at=clock_timestamp() WHERE run_id=%s",
            (source_id,),
        )
        ExecutionStore._event(connection, source_id, "run.cancelled", {})
        ExecutionStore._event(connection, source_id, "run.retried", {"replacement_run_id": str(replacement["id"]),
                                                                  "target_device_id": target_id})
        ExecutionStore._event(connection, replacement["id"], "run.retried_from", {"source_run_id": str(source_id)})
        audit_event(connection, None, "run.retried", str(source_id),
                    {"run_id": str(replacement["id"]), "workflow_id": source["workflow_id"],
                     "workflow_version": source["workflow_version"]}, category="execution")
        return {**summary, "status": "replayed", "run_id": str(replacement["id"]),
                "source_status": "cancelled"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Submit replacements and cancel their queued sources")
    parser.add_argument("--target", default="local-emulator")
    args = parser.parse_args()
    dsn = os.getenv("EMULYTIX_DATABASE_URL")
    if not dsn:
        raise ValueError("EMULYTIX_DATABASE_URL is required inside the console API environment")
    store = RunStore(dsn)
    for source_id in SOURCE_RUNS:
        print(json.dumps(replay_one(store, source_id, args.target, apply=args.apply)), flush=True)


if __name__ == "__main__":
    try:
        main()
    except psycopg.Error as exc:
        print(json.dumps({"error": "Database unavailable", "sqlstate": exc.sqlstate}), flush=True)
        raise SystemExit(1) from None
    except (ValueError, HTTPException) as exc:
        message = exc.detail if isinstance(exc, HTTPException) else str(exc)
        print(json.dumps({"error": message}), flush=True)
        raise SystemExit(1) from None
