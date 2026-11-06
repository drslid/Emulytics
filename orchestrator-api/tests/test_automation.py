from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException

from app.automation_models import RecipeInput, ScheduleInput
from app.automation_store import AutomationStore, next_occurrences
from app.run_models import DeviceRegistration, WorkflowRegistration
from app.run_store import RunStore
from test_authentication import auth_store, auth_client, create_enabled, current_code, PASSWORD
from conftest import CONTROL_TOKEN


def test_cron_timezone_and_dst_are_explicit():
    start = datetime(2026, 3, 28, 8, tzinfo=timezone.utc)
    dates = next_occurrences("0 9 * * *", "Europe/Paris", start, 3)
    assert dates[0] == datetime(2026, 3, 29, 7, tzinfo=timezone.utc)
    assert dates[1] == datetime(2026, 3, 30, 7, tzinfo=timezone.utc)
    # A nonexistent local time is skipped, a repeated local time executes once.
    dates = next_occurrences("30 2 * * *", "Europe/Paris", start, 2)
    assert dates[0] == datetime(2026, 3, 30, 0, 30, tzinfo=timezone.utc)
    dates = next_occurrences("30 2 * * *", "Europe/Paris", datetime(2026, 10, 24, 23, tzinfo=timezone.utc), 2)
    assert dates == [datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc), datetime(2026, 10, 26, 1, 30, tzinfo=timezone.utc)]


@pytest.mark.parametrize("cron,tz", [("* * * * * *", "UTC"), ("0 9 * * *", "Mars/Olympus"), ("0 9 31 2 *", "UTC"), ("nonsense", "UTC"), ("R R * * *", "UTC")])
def test_invalid_schedules_are_rejected(cron, tz):
    with pytest.raises(HTTPException) as error:
        next_occurrences(cron, tz)
    assert error.value.status_code == 422


def recipe(workflow_payload):
    return RecipeInput(name="  Mon parcours football  ", instructions="Rechercher le football", steps=workflow_payload["steps"])


def test_draft_publish_revision_and_driver_validation(database_dsn, workflow_payload):
    store = AutomationStore(database_dsn)
    saved = store.create_recipe(recipe(workflow_payload), None)
    assert saved["name"] == "Mon parcours football"
    published = store.publish_recipe(saved["id"], 1, None)
    assert published["latest_version"] == 1
    assert published["status"] == "published"
    assert store.publish_recipe(saved["id"], 1, None)["latest_version"] == 1
    changed = recipe(workflow_payload)
    changed.name = "Nouveau nom"
    assert store.update_recipe(saved["id"], 1, changed, None)["revision"] == 2
    assert RunStore(database_dsn).get_workflow(saved["workflow_id"], 1)["name"] == "Mon parcours football"
    with pytest.raises(HTTPException) as error:
        store.update_recipe(saved["id"], 1, changed, None)
    assert error.value.status_code == 409
    assert store.publish_recipe(saved["id"], 2, None)["latest_version"] == 2
    assert RunStore(database_dsn).get_workflow(saved["workflow_id"], 2)["name"] == "Nouveau nom"
    assert RunStore(database_dsn).get_workflow(saved["workflow_id"], 1)["name"] == "Mon parcours football"
    changed.steps[0].args = {"keycode": "unsafe"}
    store.update_recipe(saved["id"], 2, changed, None)
    with pytest.raises(HTTPException) as error:
        store.publish_recipe(saved["id"], 3, None)
    assert error.value.status_code == 422
    assert len(RunStore(database_dsn).list_workflows(100, 0)) == 2


def schedule_fixture(database_dsn, workflow_payload):
    actor = uuid4()
    with psycopg.connect(database_dsn) as connection:
        connection.execute("INSERT INTO auth_users(id,username,display_name,password_hash,role,active,totp_enabled,totp_secret) VALUES (%s,'scheduler-owner','Scheduler owner','not-a-real-hash','builder',true,true,'test-encrypted')", (actor,))
    runs = RunStore(database_dsn)
    runs.register_device(DeviceRegistration(device_id="scheduled-phone", host_id="host", serial="emulator-5554", kind="emulator"))
    runs.register_workflow(WorkflowRegistration(**workflow_payload))
    store = AutomationStore(database_dsn)
    saved = store.create_schedule(ScheduleInput(name="Every minute", workflow_id="go-home", workflow_version=1, device_ids=["scheduled-phone"], max_concurrency=1, cron="* * * * *", timezone="Europe/Paris"), actor)
    with psycopg.connect(database_dsn) as connection:
        connection.execute("UPDATE automation_schedules SET next_run_at=clock_timestamp() - interval '1 second' WHERE id=%s", (saved["id"],))
    return store, saved, actor


def test_concurrent_scheduler_ticks_submit_exactly_once(database_dsn, workflow_payload):
    store, saved, _ = schedule_fixture(database_dsn, workflow_payload)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: store.dispatch_due(), range(4)))
    assert len(RunStore(database_dsn).list_runs(100, 0)) == 1
    current = store.list_schedules(100, 0)["items"][0]
    assert current["last_run_id"] is not None
    assert current["next_run_at"] > datetime.now(timezone.utc)


def test_scheduler_replay_after_submit_commit_before_cursor_advance(database_dsn, workflow_payload, monkeypatch):
    store, _, _ = schedule_fixture(database_dsn, workflow_payload)
    original = store._after_submission
    monkeypatch.setattr(store, "_after_submission", lambda *args: (_ for _ in ()).throw(RuntimeError("injected crash")))
    with pytest.raises(RuntimeError):
        store.dispatch_due()
    assert len(RunStore(database_dsn).list_runs(100, 0)) == 1
    monkeypatch.setattr(store, "_after_submission", original)
    assert store.dispatch_due() == 1
    assert len(RunStore(database_dsn).list_runs(100, 0)) == 1


@pytest.mark.parametrize("change", ["active=false", "role='viewer'", "password_change_required=true", "totp_enabled=false"])
def test_scheduler_rechecks_owner_permission(database_dsn, workflow_payload, change):
    store, _, actor = schedule_fixture(database_dsn, workflow_payload)
    with psycopg.connect(database_dsn) as connection:
        connection.execute(f"UPDATE auth_users SET {change} WHERE id=%s", (actor,))
    assert store.dispatch_due() == 0
    assert RunStore(database_dsn).list_runs(100, 0) == []
    current = store.list_schedules(100, 0)["items"][0]
    assert not current["enabled"]
    assert current["last_error"] == "owner_not_authorized"


def test_pause_and_resume_skip_missed_occurrences(database_dsn, workflow_payload):
    store, saved, actor = schedule_fixture(database_dsn, workflow_payload)
    assert not store.set_schedule_enabled(saved["id"], False, actor)["enabled"]
    assert store.dispatch_due() == 0
    resumed = store.set_schedule_enabled(saved["id"], True, actor)
    assert resumed["next_run_at"] > datetime.now(timezone.utc)
    assert store.dispatch_due() == 0


def test_schedule_creation_retries_are_concurrent_and_idempotent(database_dsn, workflow_payload):
    store, _, actor = schedule_fixture(database_dsn, workflow_payload)
    request_id = str(uuid4())
    payload = ScheduleInput(name="Retry-safe", workflow_id="go-home", workflow_version=1,
                            device_ids=["scheduled-phone"], max_concurrency=1, cron="0 9 * * *",
                            timezone="Europe/Paris", request_id=request_id)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.create_schedule(payload, actor), range(4)))
    assert {str(item["id"]) for item in results} == {request_id}
    assert all(item == results[0] for item in results)
    with psycopg.connect(database_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM automation_schedules WHERE id=%s", (request_id,)).fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM audit_log WHERE action='schedule.created' AND entity_id=%s", (request_id,)).fetchone()[0] == 1
    changed = payload.model_copy(update={"name": "Different payload"})
    with pytest.raises(HTTPException) as error:
        store.create_schedule(changed, actor)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        store.create_schedule(payload, uuid4())
    assert error.value.status_code == 409


def test_schedule_replay_precedes_future_cron_and_reference_validation(database_dsn, workflow_payload, monkeypatch):
    from app import automation_store
    store, _, actor = schedule_fixture(database_dsn, workflow_payload)
    payload = ScheduleInput(name="Committed before lost response", workflow_id="go-home", workflow_version=1,
                            device_ids=["scheduled-phone"], max_concurrency=1, cron="0 9 * * *",
                            timezone="Europe/Paris", request_id=str(uuid4()))
    committed = store.create_schedule(payload, actor)
    with psycopg.connect(database_dsn) as connection:
        connection.execute("DELETE FROM devices WHERE device_id='scheduled-phone'")
    def unavailable(*args, **kwargs):
        raise AssertionError("A replay must not recompute a future CRON occurrence")
    monkeypatch.setattr(automation_store, "next_occurrences", unavailable)
    assert store.create_schedule(payload, actor) == committed


def test_recipe_routes_are_usable_and_revision_guarded(control_client, workflow_payload):
    response = control_client.post("/console/recipes", json=recipe(workflow_payload).model_dump(mode="json", by_alias=True))
    assert response.status_code == 201, response.text
    saved = response.json()
    assert control_client.post(f"/console/recipes/{saved['id']}/publish", json={"revision": 1}).status_code == 200
    update = {**recipe(workflow_payload).model_dump(mode="json", by_alias=True), "revision": 1}
    assert control_client.patch(f"/console/recipes/{saved['id']}", json=update).status_code == 200
    assert control_client.post(f"/console/recipes/{saved['id']}/publish", json={"revision": 1}).status_code == 409
    assert control_client.get("/console/recipes").json()["total"] == 1
    assert control_client.post("/console/schedules/preview", json={"cron": "0 9 * * *", "timezone": "Europe/Paris"}).status_code == 200
    assert control_client.post("/console/schedules/preview", json={"cron": "* * * * * *", "timezone": "Europe/Paris"}).status_code == 422


def test_builder_authoring_operator_execution_and_draft_privacy(auth_client, auth_store, workflow_payload):
    builder, secret = create_enabled(auth_store, "builder-one")
    with auth_store.connect() as connection:
        connection.execute("UPDATE auth_users SET role='builder' WHERE id=%s", (builder["id"],))
    auth_client.post("/auth/login", json={"username": "builder-one", "password": PASSWORD})
    assert auth_client.post("/auth/verify", json={"code": current_code(auth_store, secret)}).status_code == 200
    response = auth_client.post("/console/recipes", json=recipe(workflow_payload).model_dump(mode="json", by_alias=True))
    assert response.status_code == 201, response.text
    saved = response.json()
    published = auth_client.post(f"/console/recipes/{saved['id']}/publish", json={"revision": 1})
    assert published.status_code == 200, published.text
    assert auth_client.post("/devices", json={"device_id": "scheduled-phone", "host_id": "host", "serial": "emulator-5554", "kind": "emulator"}, headers={"Authorization": f"Bearer {CONTROL_TOKEN}"}).status_code == 201
    scheduled = auth_client.post("/console/schedules", json={"name": "  Football chaque matin  ", "workflow_id": saved["workflow_id"], "workflow_version": 1, "device_ids": ["scheduled-phone"], "max_concurrency": 1, "cron": "0 9 * * *", "timezone": "Europe/Paris"})
    assert scheduled.status_code == 201, scheduled.text
    schedule_id = scheduled.json()["id"]
    assert scheduled.json()["name"] == "Football chaque matin"
    assert auth_client.patch(f"/console/schedules/{schedule_id}", json={"enabled": False}).json()["enabled"] is False
    auth_client.post("/auth/logout", json={})
    operator, secret = create_enabled(auth_store, "operator-one")
    with auth_store.connect() as connection:
        connection.execute("UPDATE auth_users SET role='operator' WHERE id=%s", (operator["id"],))
    auth_client.post("/auth/login", json={"username": "operator-one", "password": PASSWORD})
    assert auth_client.post("/auth/verify", json={"code": current_code(auth_store, secret)}).status_code == 200
    assert auth_client.get("/console/recipes").json()["items"] == []
    assert auth_client.post("/console/recipes", json=recipe(workflow_payload).model_dump(mode="json", by_alias=True)).status_code == 403
    assert auth_client.post(f"/console/recipes/{saved['id']}/publish", json={"revision": 1}).status_code == 403
    assert auth_client.get("/console/schedules").status_code == 200
    assert auth_client.request("DELETE", f"/console/schedules/{schedule_id}", json={}).status_code == 204
