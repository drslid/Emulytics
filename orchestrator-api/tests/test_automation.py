from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException

from app.android_driver import AndroidDriver
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


def test_run_authoring_create_recipe_replays_the_same_draft(control_client, database_dsn, workflow_payload):
    payload = {**recipe(workflow_payload).model_dump(mode="json", by_alias=True), "request_id": str(uuid4())}
    first = control_client.post("/console/recipes", json=payload)
    replay = control_client.post("/console/recipes", json=payload)
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json() and first.json()["id"] == payload["request_id"]
    assert control_client.post("/console/recipes", json={**payload, "name": "Different"}).status_code == 409
    with RunStore(database_dsn).connect() as connection:
        assert connection.execute("SELECT count(*) AS n FROM audit_log WHERE action='recipe.created'").fetchone()["n"] == 1


def test_run_authoring_update_only_replays_exact_next_revision(control_client, database_dsn, workflow_payload):
    initial = recipe(workflow_payload).model_dump(mode='json', by_alias=True)
    response = control_client.post('/console/recipes', json=initial)
    endpoint = f"/console/recipes/{response.json()['id']}"
    update = {**initial, 'name': 'Version révisée', 'revision': 1, 'accept_replay': True}
    first = control_client.patch(endpoint, json=update)
    replay = control_client.patch(endpoint, json=update)
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json() and first.json()['revision'] == 2
    assert control_client.patch(endpoint, json={**update, 'name': 'Autre modification'}).status_code == 409
    assert control_client.patch(endpoint, json={**update, 'accept_replay': False}).status_code == 409
    assert control_client.patch(endpoint, json={**update, 'revision': 2}).status_code == 200
    assert control_client.patch(endpoint, json=update).status_code == 409
    with RunStore(database_dsn).connect() as connection:
        assert connection.execute("SELECT count(*) AS n FROM audit_log WHERE action='recipe.updated'").fetchone()['n'] == 2


def test_builtin_workflow_can_be_opened_as_a_draft(control_client, database_dsn):
    builtin = WorkflowRegistration.model_validate_json(
        (Path(__file__).resolve().parents[2] / "workflows/chrome-wikipedia-football.v1.json").read_text()
    )
    runs = RunStore(database_dsn)
    runs.register_workflow(builtin)
    before = runs.get_workflow(builtin.workflow_id, 1)
    response = control_client.post("/console/recipes/from-workflow", json={
        "workflow_id": builtin.workflow_id, "version": 1,
        "name": " Recherche Wikipédia ", "instructions": " Ouvrir Chrome et rechercher football ",
    })
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["workflow_id"] == builtin.workflow_id
    assert draft["status"] == "draft"
    assert draft["definition"]["steps"] == before["steps"]
    assert draft["name"] == "Recherche Wikipédia"
    assert draft["instructions"] == "Ouvrir Chrome et rechercher football"
    assert runs.get_workflow(builtin.workflow_id, 1) == before
    draft["definition"]["steps"][-1]["timeout_ms"] = 25_000
    update = {"name": draft["name"], "instructions": draft["instructions"], "revision": draft["revision"], **draft["definition"]}
    assert control_client.patch(f"/console/recipes/{draft['id']}", json=update).status_code == 200
    published = control_client.post(f"/console/recipes/{draft['id']}/publish", json={"revision": 2})
    assert published.status_code == 200, published.text
    assert published.json()["latest_version"] == 2
    assert runs.get_workflow(builtin.workflow_id, 2)["steps"][-1]["timeout_ms"] == 25_000
    assert runs.get_workflow(builtin.workflow_id, 1) == before


def test_workflow_import_copies_publication_metadata_and_preserves_existing_draft(database_dsn, workflow_payload):
    store = AutomationStore(database_dsn)
    store.register_workflow(WorkflowRegistration(**workflow_payload))
    with store.connect() as connection:
        connection.execute("INSERT INTO automation_publications(workflow_id,version,name,instructions) VALUES('go-home',1,'Parcours publié','Consigne publiée')")
    draft = store.recipe_from_workflow("go-home", 1, None, name="Autre nom", instructions="Autre consigne")
    assert draft["name"] == "Parcours publié"
    assert draft["instructions"] == "Consigne publiée"
    changed = recipe(workflow_payload)
    changed.steps[0].timeout_ms = 25_000
    saved = store.update_recipe(draft["id"], draft["revision"], changed, None)
    assert store.recipe_from_workflow("go-home", 1, None, name="Écrasement", instructions="Écrasement") == saved
    assert store.list_recipes(100, 0)["total"] == 1


def test_workflow_import_is_concurrent_and_audited_once(database_dsn, workflow_payload):
    store = AutomationStore(database_dsn)
    store.register_workflow(WorkflowRegistration(**workflow_payload))
    with ThreadPoolExecutor(max_workers=4) as pool:
        drafts = list(pool.map(lambda _: store.recipe_from_workflow("go-home", 1, None), range(4)))
    assert all(draft == drafts[0] for draft in drafts)
    assert drafts[0]["name"] == "go-home"
    assert drafts[0]["instructions"] == ""
    assert store.list_recipes(100, 0)["total"] == 1
    with store.connect() as connection:
        assert connection.execute("SELECT count(*) AS n FROM audit_log WHERE action='recipe.created'").fetchone()["n"] == 1


def test_imported_draft_publishes_after_latest_version_and_keeps_history(database_dsn, workflow_payload):
    store, schedule, _ = schedule_fixture(database_dsn, workflow_payload)
    store.dispatch_due()
    old_runs = store.list_runs(100, 0)
    with store.connect() as connection:
        original = connection.execute("SELECT * FROM workflows WHERE workflow_id='go-home' AND version=1").fetchone()
    store.register_workflow(WorkflowRegistration(**{**workflow_payload, "version": 3}))
    draft = store.recipe_from_workflow("go-home", 1, None)
    changed = recipe(workflow_payload)
    changed.steps[0].timeout_ms = 25_000
    saved = store.update_recipe(draft["id"], draft["revision"], changed, None)
    # A separately registered newer publication must not make this draft reuse a version.
    store.register_workflow(WorkflowRegistration(**{**workflow_payload, "version": 5}))
    with ThreadPoolExecutor(max_workers=2) as pool:
        published = list(pool.map(lambda _: store.publish_recipe(saved["id"], saved["revision"], None), range(2)))
    assert all(value["latest_version"] == 6 for value in published)
    assert store.get_workflow("go-home", 6)["steps"][0]["timeout_ms"] == 25_000
    assert store.list_runs(100, 0) == old_runs
    assert store.list_schedules(100, 0)["items"][0]["workflow_version"] == schedule["workflow_version"] == 1
    with store.connect() as connection:
        assert connection.execute("SELECT * FROM workflows WHERE workflow_id='go-home' AND version=1").fetchone() == original
        assert connection.execute("SELECT count(*) AS n FROM automation_publications WHERE workflow_id='go-home'").fetchone()["n"] == 1


def test_workflow_import_route_validates_identity_and_missing_source(control_client, database_dsn):
    assert control_client.post("/console/recipes/from-workflow", json={"workflow_id": "missing", "version": 1}).status_code == 404
    for payload in ({"workflow_id": "bad/id", "version": 1}, {"workflow_id": "missing", "version": 0},
                    {"workflow_id": "missing", "version": "1"}, {"workflow_id": "missing", "version": 1, "unexpected": True},
                    {"workflow_id": "missing", "version": 1, "name": " "}, {"workflow_id": "missing", "version": 1, "name": "x" * 121},
                    {"workflow_id": "missing", "version": 1, "instructions": "x" * 8001}):
        assert control_client.post("/console/recipes/from-workflow", json=payload).status_code == 422
    assert AutomationStore(database_dsn).list_recipes(100, 0)["total"] == 0


def test_publication_collision_rolls_back_and_can_be_retried(database_dsn, workflow_payload, monkeypatch):
    store = AutomationStore(database_dsn)
    saved = store.create_recipe(recipe(workflow_payload), None)
    validate_step = AndroidDriver.validate_step

    def register_competing_version(step):
        validate_step(step)
        store.register_workflow(WorkflowRegistration(**{**workflow_payload, "workflow_id": saved["workflow_id"]}))

    monkeypatch.setattr(AndroidDriver, "validate_step", register_competing_version)
    with pytest.raises(HTTPException) as error:
        store.publish_recipe(saved["id"], 1, None)
    assert error.value.status_code == 409
    assert store.list_recipes(100, 0)["items"][0] == saved
    with store.connect() as connection:
        assert connection.execute("SELECT count(*) AS n FROM automation_publications").fetchone()["n"] == 0
    monkeypatch.setattr(AndroidDriver, "validate_step", validate_step)
    assert store.publish_recipe(saved["id"], 1, None)["latest_version"] == 2


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


def test_failed_due_schedules_do_not_starve_a_later_valid_schedule(database_dsn, workflow_payload, monkeypatch):
    store, valid, actor = schedule_fixture(database_dsn, workflow_payload)
    store.register_device(DeviceRegistration(device_id='unprepared-phone',host_id='host',serial='emulator-5556',kind='emulator'))
    with store.connect() as connection:
        connection.execute("INSERT INTO managed_emulators(id,device_id,host_id,slot,application_ids,create_key,create_hash) "
                           "VALUES(%s,'unprepared-phone','host',1,'[]',%s,'test-hash')",(uuid4(),str(uuid4())))
    rejected = [store.create_schedule(ScheduleInput(name=f'Not ready {index}',workflow_id='go-home',workflow_version=1,
        device_ids=['unprepared-phone'],max_concurrency=1,cron='* * * * *'),actor)['id'] for index in range(20)]
    with store.connect() as connection:
        connection.execute("UPDATE automation_schedules SET next_run_at=clock_timestamp()-interval '2 hours' WHERE id=ANY(%s)",(rejected,))
        connection.execute("UPDATE automation_schedules SET next_run_at=clock_timestamp()-interval '1 hour' WHERE id=%s",(valid['id'],))
        due = {row['id']:row['next_run_at'] for row in connection.execute('SELECT id,next_run_at FROM automation_schedules').fetchall()}
    # Keep the next slot beyond this fairness check, even across minute boundaries.
    monkeypatch.setattr('app.automation_store.next_occurrences',
                        lambda expression, zone, after, count: [after + timedelta(hours=1)])
    assert store.dispatch_due()==0
    assert store.dispatch_due()==1
    assert store.dispatch_due()==0
    runs = store.list_runs(100,0)
    assert len(runs)==1 and runs[0]['device_ids']==['scheduled-phone']
    assert store.get_run(runs[0]['id'])['idempotency_key']==f"schedule:{valid['id']}:{due[valid['id']].isoformat()}"
    with store.connect() as connection:
        blocked = connection.execute('SELECT id,next_run_at,last_error FROM automation_schedules WHERE id=ANY(%s)',(rejected,)).fetchall()
        assert all(row['next_run_at']==due[row['id']] and row['last_error']=='dispatch_failed' for row in blocked)


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
    assert auth_client.post("/console/recipes/from-workflow", json={"workflow_id": saved["workflow_id"], "version": 1}).json()["id"] == saved["id"]
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
    assert auth_client.post("/console/recipes/from-workflow", json={"workflow_id": saved["workflow_id"], "version": 1}).status_code == 403
    assert auth_client.post(f"/console/recipes/{saved['id']}/publish", json={"revision": 1}).status_code == 403
    assert auth_client.get("/console/schedules").status_code == 200
    assert auth_client.request("DELETE", f"/console/schedules/{schedule_id}", json={}).status_code == 204
    with auth_store.connect() as connection:
        connection.execute("UPDATE auth_users SET role='viewer' WHERE id=%s", (operator["id"],))
    assert auth_client.post("/console/recipes/from-workflow", json={"workflow_id": saved["workflow_id"], "version": 1}).status_code == 403
