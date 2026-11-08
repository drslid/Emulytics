from uuid import UUID
import hashlib
import json

import psycopg
from psycopg.types.json import Jsonb
import pytest


def test_active_cancellation_is_acknowledged_then_completed_by_owner(registered, run_payload, database_dsn):
    from app.execution_store import ExecutionStore
    store = ExecutionStore(database_dsn)
    run = registered.post("/runs", json=run_payload).json()
    execution_id = UUID(run["executions"][0]["id"])
    grant = store.claim(execution_id, "worker-test", 30, host_id="host-1")
    response = registered.post(f"/runs/{run['id']}/cancel")
    assert response.status_code == 202
    assert response.json()["status"] == "running"
    assert response.json()["cancel_requested"] is True
    assert store.state(execution_id, "worker-test", grant["lease_epoch"])["cancel_requested"]
    assert not store.renew(execution_id, "worker-test", grant["lease_epoch"], 30)
    assert registered.post(f"/runs/{run['id']}/cancel").status_code == 202
    assert store.finish(execution_id, "worker-test", grant["lease_epoch"], "cancelled")
    assert registered.get(f"/runs/{run['id']}").json()["status"] == "cancelled"
    events = registered.get(f"/runs/{run['id']}/events").json()["items"]
    assert sum(event["type"] == "run.cancel_requested" for event in events) == 1


def test_execution_action_journal_is_available_to_authenticated_operator(registered, run_payload, database_dsn):
    from app.execution_store import ExecutionStore
    store = ExecutionStore(database_dsn)
    run = registered.post("/runs", json=run_payload).json()
    execution_id = UUID(run["executions"][0]["id"])
    grant = store.claim(execution_id, "worker-test", 30)
    journal = store.before_action(execution_id, "worker-test", grant["lease_epoch"], "home", {"transport": "adb"}, False)
    store.finish_action(execution_id, "worker-test", grant["lease_epoch"], journal, "done", {"verified": True})
    response = registered.get(f"/executions/{execution_id}/actions")
    assert response.status_code == 200
    assert response.json()["items"][0]["status"] == "done"
    assert response.json()["items"][0]["evidence"] == {"verified": True}
    assert registered.get(f"/executions/{execution_id}/actions?offset=1").json()["items"] == []


@pytest.mark.parametrize("path", ["/android/status", "/runtime-capabilities"])
def test_direct_runtime_control_routes_are_removed(client, path):
    assert client.get(path).status_code == 404


def test_workflow_from_previous_schema_remains_idempotent(control_client, workflow_payload, database_dsn):
    # This is the normalized persisted envelope before optional `when` was introduced.
    old = {**workflow_payload, "recovery_budget": 0, "steps": [{
        **workflow_payload["steps"][0], "selectors": [], "timeout_ms": 10_000,
        "non_idempotent": False, "recovery_budget": 0, "recovery_actions": [], "verify_after_crash": None,
    }]}
    digest = hashlib.sha256(json.dumps(old, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with psycopg.connect(database_dsn) as connection:
        connection.execute("INSERT INTO workflows (workflow_id,version,definition,content_hash) VALUES (%s,%s,%s,%s)",
                           (old["workflow_id"], old["version"], Jsonb(old), digest))
    assert control_client.post("/workflows", json=workflow_payload).status_code == 200
