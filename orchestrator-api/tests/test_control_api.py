from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
import importlib
import json
import threading
from uuid import UUID

from fastapi.testclient import TestClient
import psycopg
import pytest

from conftest import CONTROL_TOKEN


def rows(dsn, statement, parameters=()):
    with psycopg.connect(dsn) as connection:
        return connection.execute(statement, parameters).fetchall()


def submit_concurrently(app, path, payloads):
    barrier = threading.Barrier(len(payloads))

    def submit(payload):
        with TestClient(app, headers={"Authorization": f"Bearer {CONTROL_TOKEN}"}) as client:
            barrier.wait(timeout=10)
            return client.post(path, json=payload)

    with ThreadPoolExecutor(max_workers=len(payloads)) as executor:
        return list(executor.map(submit, payloads))


@pytest.mark.parametrize("method,path", [
    ("GET", "/devices"), ("POST", "/devices"),
    ("POST", "/workflows"), ("GET", "/workflows/go-home/versions/1"),
    ("GET", "/runs"), ("POST", "/runs"),
    ("GET", "/runs/ffffffff-ffff-4fff-bfff-ffffffffffff"),
    ("POST", "/runs/ffffffff-ffff-4fff-bfff-ffffffffffff/cancel"),
    ("GET", "/runs/ffffffff-ffff-4fff-bfff-ffffffffffff/events"),
    ("GET", "/executions/ffffffff-ffff-4fff-bfff-ffffffffffff/actions"),
])
def test_control_routes_require_authentication(client, method, path):
    response = client.request(method, path, json={} if method == "POST" else None)
    assert response.status_code == 401


def test_control_routes_reject_an_incorrect_token(client):
    response = client.get("/runs", headers={"Authorization": "Bearer incorrect"})
    assert response.status_code == 401


def test_database_configuration_is_required_without_breaking_legacy_sessions(client):
    response = client.get("/runs", headers={"Authorization": f"Bearer {CONTROL_TOKEN}"})
    assert response.status_code == 503
    created = client.post("/sessions", json={"name": "Legacy compatibility"})
    assert created.status_code == 200
    response = client.get(f"/sessions/{created.json()['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == "Legacy compatibility"


def test_openapi_documents_new_and_legacy_routes(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    for path in [
        "/devices", "/workflows", "/workflows/{workflow_id}/versions/{version}",
        "/runs", "/runs/{run_id}", "/runs/{run_id}/cancel", "/runs/{run_id}/events",
        "/sessions", "/sessions/{session_id}",
    ]:
        assert path in paths


def test_openapi_describes_required_run_response_fields_and_states(client):
    document = client.get("/openapi.json").json()
    response = document["paths"]["/runs/{run_id}"]["get"]["responses"]["200"]
    schema = response["content"]["application/json"]["schema"]
    assert "$ref" in schema

    def resolved(value):
        if "$ref" in value:
            return document["components"]["schemas"][value["$ref"].rsplit("/", 1)[1]]
        return value

    run = resolved(schema)
    required = {
        "id", "status", "workflow_id", "workflow_version", "device_ids",
        "max_concurrency", "parameters", "executions", "created_at", "updated_at", "cancel_requested",
    }
    assert required <= set(run["required"])
    assert {"queued", "cancelled"} <= set(resolved(run["properties"]["status"])["enum"])
    assert run["properties"]["created_at"]["format"] == "date-time"
    assert run["properties"]["updated_at"]["format"] == "date-time"
    execution = resolved(run["properties"]["executions"]["items"])
    assert {"id", "device_id", "status"} <= set(execution["required"])
    assert {"queued", "cancelled"} <= set(resolved(execution["properties"]["status"])["enum"])


def test_migration_is_repeatable_without_deleting_data(database_dsn, registered, run_payload):
    from app.migrate import migrate

    created = registered.post("/runs", json=run_payload)
    assert created.status_code == 202, created.text
    before = rows(database_dsn, "SELECT version, checksum FROM schema_migrations ORDER BY version")
    assert before
    migrate(database_dsn)
    migrate(database_dsn)
    assert rows(database_dsn, "SELECT version, checksum FROM schema_migrations ORDER BY version") == before
    assert registered.get(f"/runs/{created.json()['id']}").json()["id"] == created.json()["id"]


def test_migration_refuses_an_applied_checksum_mismatch(database_dsn):
    from app.migrate import migrate

    with psycopg.connect(database_dsn) as connection:
        connection.execute("UPDATE schema_migrations SET checksum = 'altered-test-checksum'")
    with pytest.raises(RuntimeError, match="migration changed"):
        migrate(database_dsn)


def test_devices_are_immutable_and_listed_with_pagination(control_client):
    device = {"device_id": "physical-1", "host_id": "host-1", "serial": "ABC123", "kind": "physical"}
    created = control_client.post("/devices", json=device)
    assert created.status_code == 201, created.text
    replay = control_client.post("/devices", json=device)
    assert replay.status_code == 200
    assert replay.json() == created.json()
    assert control_client.post("/devices", json={**device, "serial": "DIFFERENT"}).status_code == 409
    page = control_client.get("/devices", params={"limit": 1, "offset": 0})
    assert page.status_code == 200
    assert page.json()["limit"] == 1
    assert page.json()["offset"] == 0
    assert len(page.json()["items"]) == 1
    assert page.json()["items"][0]["serial"] == "ABC123"
    assert control_client.get("/devices", params={"limit": 1, "offset": 1}).json()["items"] == []


def test_one_host_serial_cannot_be_registered_under_two_device_ids(control_client):
    device = {"device_id": "physical-1", "host_id": "host-1", "serial": "ABC123", "kind": "physical"}
    assert control_client.post("/devices", json=device).status_code == 201
    assert control_client.post("/devices", json={**device, "device_id": "physical-2"}).status_code == 409
    assert len(control_client.get("/devices").json()["items"]) == 1


def test_workflow_versions_are_immutable(control_client, workflow_payload):
    created = control_client.post("/workflows", json=workflow_payload)
    assert created.status_code == 201, created.text
    replay = control_client.post("/workflows", json=workflow_payload)
    assert replay.status_code == 200
    assert replay.json() == created.json()
    altered = deepcopy(workflow_payload)
    altered["steps"][0]["args"]["keycode"] = "KEYCODE_BACK"
    assert control_client.post("/workflows", json=altered).status_code == 409
    fetched = control_client.get("/workflows/go-home/versions/1")
    assert fetched.status_code == 200
    assert fetched.json() == created.json()
    assert control_client.get("/workflows/go-home/versions/2").status_code == 404
    second = {**workflow_payload, "version": 2}
    assert control_client.post("/workflows", json=second).status_code == 201


def test_create_run_freezes_devices_and_creates_queued_executions(registered, run_payload, database_dsn):
    response = registered.post("/runs", json=run_payload)
    assert response.status_code == 202, response.text
    run = response.json()
    UUID(run["id"])
    assert run["status"] == "queued"
    assert run["cancel_requested"] is False
    for field in ["workflow_id", "workflow_version", "device_ids", "max_concurrency", "parameters"]:
        assert run[field] == run_payload[field]
    assert datetime.fromisoformat(run["created_at"]).tzinfo is not None
    assert datetime.fromisoformat(run["updated_at"]).tzinfo is not None
    assert len(run["executions"]) == 1
    execution = run["executions"][0]
    UUID(execution["id"])
    assert execution["device_id"] == "phone-1"
    assert execution["status"] == "queued"
    assert rows(database_dsn, "SELECT status FROM executions WHERE run_id = %s", (run["id"],)) == [("queued",)]
    assert registered.get(f"/runs/{run['id']}").json() == run


def test_run_idempotency_replays_same_intent_and_rejects_different_payload(registered, run_payload, database_dsn):
    first = registered.post("/runs", json=run_payload)
    assert first.status_code == 202, first.text
    replay = registered.post("/runs", json=run_payload)
    assert replay.status_code == 202
    assert replay.json()["id"] == first.json()["id"]
    conflict = registered.post("/runs", json={**run_payload, "parameters": {"different": True}})
    assert conflict.status_code == 409
    assert rows(database_dsn, "SELECT count(*) FROM runs") == [(1,)]
    assert rows(database_dsn, "SELECT count(*) FROM executions") == [(1,)]
    assert rows(database_dsn, "SELECT count(*) FROM run_events") == [(1,)]


@pytest.mark.parametrize("change", [
    {"workflow_id": "unknown-workflow"},
    {"device_ids": ["unknown-device"]},
])
def test_idempotency_conflict_takes_precedence_over_unknown_references(registered, run_payload, database_dsn, change):
    original = registered.post("/runs", json=run_payload)
    assert original.status_code == 202
    response = registered.post("/runs", json={**run_payload, **change})
    assert response.status_code == 409, response.text
    assert rows(database_dsn, "SELECT count(*) FROM runs") == [(1,)]
    assert rows(database_dsn, "SELECT count(*) FROM executions") == [(1,)]
    assert rows(database_dsn, "SELECT count(*) FROM run_events") == [(1,)]


def test_parameter_object_key_order_does_not_change_idempotent_intent(registered, run_payload):
    first = registered.post("/runs", json={**run_payload, "parameters": {"a": 1, "b": {"x": 2, "y": 3}}})
    assert first.status_code == 202
    replay = registered.post("/runs", json={**run_payload, "parameters": {"b": {"y": 3, "x": 2}, "a": 1}})
    assert replay.status_code == 202
    assert replay.json()["id"] == first.json()["id"]


def test_concurrent_duplicate_submissions_create_one_run(registered, run_payload, database_dsn, app_module):
    responses = submit_concurrently(app_module.app, "/runs", [run_payload] * 8)
    assert [response.status_code for response in responses] == [202] * 8
    assert len({response.json()["id"] for response in responses}) == 1
    assert rows(database_dsn, "SELECT count(*) FROM runs") == [(1,)]
    assert rows(database_dsn, "SELECT count(*) FROM executions") == [(1,)]
    assert rows(database_dsn, "SELECT count(*) FROM run_events") == [(1,)]


def test_concurrent_same_key_with_different_content_has_one_winner(registered, run_payload, database_dsn, app_module):
    responses = submit_concurrently(
        app_module.app, "/runs",
        [{**run_payload, "parameters": {"winner": index}} for index in range(2)],
    )
    assert sorted(response.status_code for response in responses) == [202, 409]
    winner = next(response.json() for response in responses if response.status_code == 202)
    assert rows(database_dsn, "SELECT parameters FROM runs") == [(winner["parameters"],)]
    assert rows(database_dsn, "SELECT count(*) FROM executions") == [(1,)]


def test_new_app_instance_reads_persisted_run(registered, run_payload, app_module):
    created = registered.post("/runs", json=run_payload)
    assert created.status_code == 202
    expected = created.json()
    restarted = importlib.reload(app_module)
    with TestClient(restarted.app, headers={"Authorization": f"Bearer {CONTROL_TOKEN}"}) as fresh:
        response = fresh.get(f"/runs/{expected['id']}")
    assert response.status_code == 200
    assert response.json() == expected


@pytest.mark.parametrize("change", [
    {"workflow_id": "unknown-workflow"},
    {"workflow_version": 2},
    {"device_ids": ["unknown-device"]},
    {"device_ids": ["phone-1", "unknown-device"]},
])
def test_unknown_references_leave_no_partial_run(registered, run_payload, database_dsn, change):
    response = registered.post("/runs", json={**run_payload, **change})
    assert response.status_code == 404, response.text
    for table in ["runs", "executions", "run_events"]:
        assert rows(database_dsn, f"SELECT count(*) FROM {table}") == [(0,)]


def test_submission_rolls_back_when_its_event_cannot_be_written(registered, run_payload, database_dsn):
    with psycopg.connect(database_dsn) as connection:
        connection.execute("""
            CREATE FUNCTION reject_run_event() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'forced test event failure'; END $$;
            CREATE TRIGGER reject_event BEFORE INSERT ON run_events
            FOR EACH ROW EXECUTE FUNCTION reject_run_event();
        """)
    response = registered.post("/runs", json=run_payload)
    assert response.status_code == 503
    assert "forced test" not in response.text
    for table in ["runs", "executions", "run_events"]:
        assert rows(database_dsn, f"SELECT count(*) FROM {table}") == [(0,)]


def test_cancel_queued_run_is_atomic_durable_and_idempotent(registered, run_payload, database_dsn):
    created = registered.post("/runs", json=run_payload)
    assert created.status_code == 202
    run_id = created.json()["id"]
    cancelled = registered.post(f"/runs/{run_id}/cancel")
    assert cancelled.status_code == 200
    result = cancelled.json()
    assert result["status"] == "cancelled"
    assert result["cancel_requested"] is True
    assert all(execution["status"] == "cancelled" for execution in result["executions"])
    replay = registered.post(f"/runs/{run_id}/cancel")
    assert replay.status_code == 200
    assert replay.json() == result
    assert rows(database_dsn, "SELECT status, cancel_requested FROM runs WHERE id = %s", (run_id,)) == [("cancelled", True)]
    assert rows(database_dsn, "SELECT status FROM executions WHERE run_id = %s", (run_id,)) == [("cancelled",)]
    assert rows(database_dsn, "SELECT sequence, type FROM run_events WHERE run_id = %s ORDER BY sequence", (run_id,)) == [(1, "run.created"), (2, "run.cancelled")]


def test_cancellation_rolls_back_when_its_event_cannot_be_written(registered, run_payload, database_dsn):
    created = registered.post("/runs", json=run_payload)
    assert created.status_code == 202
    run_id = created.json()["id"]
    with psycopg.connect(database_dsn) as connection:
        connection.execute("""
            CREATE FUNCTION reject_cancel_event() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'forced test cancellation failure'; END $$;
            CREATE TRIGGER reject_event BEFORE INSERT ON run_events
            FOR EACH ROW WHEN (NEW.type = 'run.cancelled') EXECUTE FUNCTION reject_cancel_event();
        """)
    response = registered.post(f"/runs/{run_id}/cancel")
    assert response.status_code == 503
    assert "forced test" not in response.text
    assert rows(database_dsn, "SELECT status, cancel_requested FROM runs WHERE id = %s", (run_id,)) == [("queued", False)]
    assert rows(database_dsn, "SELECT status FROM executions WHERE run_id = %s", (run_id,)) == [("queued",)]
    assert rows(database_dsn, "SELECT count(*) FROM run_events WHERE run_id = %s", (run_id,)) == [(1,)]


def test_concurrent_cancellations_append_one_cancellation_event(registered, run_payload, database_dsn, app_module):
    created = registered.post("/runs", json=run_payload)
    assert created.status_code == 202
    run_id = created.json()["id"]
    responses = submit_concurrently(app_module.app, f"/runs/{run_id}/cancel", [{}] * 6)
    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["status"] == "cancelled" for response in responses)
    assert rows(database_dsn, "SELECT count(*) FROM run_events WHERE run_id = %s", (run_id,)) == [(2,)]


def test_active_execution_cannot_be_reported_cancelled_without_host_control(registered, run_payload, database_dsn):
    created = registered.post("/runs", json=run_payload)
    assert created.status_code == 202
    run_id = created.json()["id"]
    with psycopg.connect(database_dsn) as connection:
        connection.execute("UPDATE runs SET status = 'running' WHERE id = %s", (run_id,))
        connection.execute("UPDATE executions SET status = 'running' WHERE run_id = %s", (run_id,))
    response = registered.post(f"/runs/{run_id}/cancel")
    assert response.status_code == 409
    assert rows(database_dsn, "SELECT status FROM runs WHERE id = %s", (run_id,)) == [("running",)]
    assert rows(database_dsn, "SELECT count(*) FROM run_events WHERE run_id = %s", (run_id,)) == [(1,)]


def test_events_are_ordered_and_cursor_filtered(registered, run_payload):
    created = registered.post("/runs", json=run_payload)
    assert created.status_code == 202
    run_id = created.json()["id"]
    assert registered.post(f"/runs/{run_id}/cancel").status_code == 200
    first = registered.get(f"/runs/{run_id}/events", params={"after": 0, "limit": 1})
    assert first.status_code == 200
    assert first.json()["limit"] == 1
    assert [(item["sequence"], item["type"]) for item in first.json()["items"]] == [(1, "run.created")]
    following = registered.get(f"/runs/{run_id}/events", params={"after": 1, "limit": 1})
    assert [(item["sequence"], item["type"]) for item in following.json()["items"]] == [(2, "run.cancelled")]
    assert registered.get(f"/runs/{run_id}/events", params={"after": 2}).json()["items"] == []


def test_event_cursor_cannot_exceed_postgresql_bigint_range(registered, run_payload):
    created = registered.post("/runs", json=run_payload)
    assert created.status_code == 202
    response = registered.get(f"/runs/{created.json()['id']}/events", params={"after": 2**63})
    assert response.status_code == 422


def test_list_runs_is_paginated(registered, run_payload):
    for index in range(3):
        response = registered.post("/runs", json={**run_payload, "idempotency_key": f"run-{index}"})
        assert response.status_code == 202
    first = registered.get("/runs", params={"limit": 2, "offset": 0}).json()
    second = registered.get("/runs", params={"limit": 2, "offset": 2}).json()
    assert first["limit"] == second["limit"] == 2
    assert first["offset"] == 0 and second["offset"] == 2
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert len({item["id"] for item in first["items"] + second["items"]}) == 3


@pytest.mark.parametrize("change", [
    {"device_ids": []},
    {"device_ids": ["phone-1", "phone-1"]},
    {"device_ids": [f"device-{number}" for number in range(101)]},
    {"max_concurrency": 0},
    {"max_concurrency": 2},
    {"workflow_version": 0},
    {"idempotency_key": ""},
    {"unexpected": "must be rejected"},
])
def test_run_inputs_are_strictly_validated(registered, run_payload, database_dsn, change):
    response = registered.post("/runs", json={**run_payload, **change})
    assert response.status_code == 422, response.text
    assert rows(database_dsn, "SELECT count(*) FROM runs") == [(0,)]


@pytest.mark.parametrize("case", ["empty", "duplicate", "too-many", "extra", "step-extra"])
def test_workflow_steps_are_bounded_and_strict(control_client, workflow_payload, case):
    payload = deepcopy(workflow_payload)
    if case == "empty":
        payload["steps"] = []
    elif case == "duplicate":
        payload["steps"] = payload["steps"] * 2
    elif case == "too-many":
        payload["steps"] = [{**payload["steps"][0], "id": f"step-{number}"} for number in range(15)]
    elif case == "extra":
        payload["unexpected"] = True
    else:
        payload["steps"][0]["unexpected"] = True
    response = control_client.post("/workflows", json=payload)
    assert response.status_code == 422, response.text


def test_non_idempotent_step_requires_an_explicit_crash_verification(control_client, workflow_payload):
    payload = deepcopy(workflow_payload)
    payload["steps"][0]["non_idempotent"] = True
    rejected = control_client.post("/workflows", json=payload)
    assert rejected.status_code == 422
    payload["steps"][0]["verify_after_crash"] = {"type": "package", "value": "com.android.launcher3"}
    assert control_client.post("/workflows", json=payload).status_code == 201


def test_workflow_version_cannot_exceed_postgresql_integer_range(control_client, workflow_payload, database_dsn):
    response = control_client.post("/workflows", json={**workflow_payload, "version": 2**31})
    assert response.status_code == 422, response.text
    assert rows(database_dsn, "SELECT count(*) FROM workflows") == [(0,)]


def test_run_workflow_version_cannot_exceed_postgresql_integer_range(registered, run_payload, database_dsn):
    response = registered.post("/runs", json={**run_payload, "workflow_version": 2**31})
    assert response.status_code == 422, response.text
    for table in ["runs", "executions", "run_events"]:
        assert rows(database_dsn, f"SELECT count(*) FROM {table}") == [(0,)]


@pytest.mark.parametrize("invalid", ["\x00", "\ud800", "\udfff"], ids=["nul", "lone-high-surrogate", "lone-low-surrogate"])
@pytest.mark.parametrize("position", ["key", "value"])
def test_run_parameters_reject_strings_postgresql_json_cannot_store(registered, run_payload, database_dsn, invalid, position):
    invalid_value = {invalid: "sentinel"} if position == "key" else {"value": invalid}
    payload = {**run_payload, "parameters": {"nested": [invalid_value]}}
    response = registered.post(
        "/runs", content=json.dumps(payload), headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, response.text
    assert all("input" not in item for item in response.json()["detail"])
    for table in ["runs", "executions", "run_events"]:
        assert rows(database_dsn, f"SELECT count(*) FROM {table}") == [(0,)]


@pytest.mark.parametrize("invalid", ["\x00", "\ud800", "\udfff"], ids=["nul", "lone-high-surrogate", "lone-low-surrogate"])
@pytest.mark.parametrize("position", ["key", "value"])
def test_workflow_arguments_reject_strings_postgresql_json_cannot_store(control_client, workflow_payload, database_dsn, invalid, position):
    payload = deepcopy(workflow_payload)
    payload["steps"][0]["args"] = {invalid: "sentinel"} if position == "key" else {"value": invalid}
    response = control_client.post(
        "/workflows", content=json.dumps(payload), headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, response.text
    assert all("input" not in item for item in response.json()["detail"])
    assert rows(database_dsn, "SELECT count(*) FROM workflows") == [(0,)]


def test_valid_unicode_is_preserved_in_arguments_and_parameters(registered, workflow_payload, run_payload):
    workflow = deepcopy(workflow_payload)
    workflow["version"] = 2
    workflow["steps"][0]["action"] = "type_text"
    workflow["steps"][0]["args"] = {"text": "Ça fonctionne 😊"}
    assert registered.post("/workflows", json=workflow).status_code == 201
    parameters = {"étiquette": "漢字 😊", "nested": [{"texte": "Français"}]}
    created = registered.post("/runs", json={**run_payload, "workflow_version": 2, "parameters": parameters})
    assert created.status_code == 202
    stored = registered.get(f"/runs/{created.json()['id']}")
    assert stored.json()["parameters"] == parameters


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_run_parameters_reject_nonfinite_json_numbers(registered, run_payload, invalid):
    payload = {**run_payload, "parameters": {"nested": [{"value": invalid}]}}
    response = registered.post(
        "/runs", content=json.dumps(payload), headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("path", [
    "/runs?limit=0", "/runs?offset=-1", "/devices?offset=-1", "/devices?limit=0",
    f"/runs?offset={2**63}", f"/devices?offset={2**63}",
])
def test_pagination_bounds_are_validated(control_client, path):
    assert control_client.get(path).status_code == 422


def test_unknown_run_has_no_events_and_cannot_be_cancelled(control_client):
    absent = "ffffffff-ffff-4fff-bfff-ffffffffffff"
    assert control_client.get(f"/runs/{absent}").status_code == 404
    assert control_client.get(f"/runs/{absent}/events").status_code == 404
    assert control_client.post(f"/runs/{absent}/cancel").status_code == 404


@pytest.mark.parametrize("path", [
    "/workflows/%00/versions/1", f"/workflows/go-home/versions/{2**31}",
])
def test_workflow_lookup_path_is_validated_before_querying_postgresql(control_client, path):
    assert control_client.get(path).status_code == 422
