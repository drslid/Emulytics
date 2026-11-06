"""Retry repair is tested against disposable PostgreSQL, never a local console."""
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from app.execution_store import ExecutionStore
from app.run_models import DeviceRegistration, RunSubmission, WorkflowRegistration
from app.run_store import RunStore
from app.telemetry import heartbeat

spec = importlib.util.spec_from_file_location("replay_pending_console", Path(__file__).resolve().parents[2] / "scripts/replay-pending-console.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


@pytest.fixture
def backlog(database_dsn):
    store = RunStore(database_dsn)
    store.register_device(DeviceRegistration(device_id="banc-de-test", host_id="bench", serial="moultiplate", kind="emulator"))
    store.register_device(DeviceRegistration(device_id="local-emulator", host_id="bench-host", serial="emulator-5554", kind="emulator"))
    store.register_workflow(WorkflowRegistration(workflow_id="chrome-wikipedia-football", version=1,
        steps=[{"id":"open","action":"open_app","args":{"package_name":"com.android.chrome"},"assert":{"type":"package","value":"com.android.chrome"}}]))
    heartbeat(database_dsn, "worker", "test-worker", "bench-host", metrics={"adb_status":"ready","devices":[{"serial":"emulator-5554","state":"device"}]})
    source = store.submit_run(RunSubmission(workflow_id="chrome-wikipedia-football", workflow_version=1,
        device_ids=["banc-de-test"], max_concurrency=1, parameters={"search":"football"}, idempotency_key=str(uuid4())))
    return store, source


def test_dry_run_preserves_original_and_parameters(backlog):
    store, source = backlog
    result = replay.replay_one(store, source["id"])
    assert result["status"] == "dry_run"
    unchanged = store.get_run(source["id"])
    assert unchanged["status"] == "queued"
    assert unchanged["device_ids"] == ["banc-de-test"]
    assert unchanged["parameters"] == {"search":"football"}
    assert len(store.list_runs(100, 0)) == 1


def test_retry_keeps_history_and_is_idempotent(backlog):
    store, source = backlog
    result = replay.replay_one(store, source["id"], apply=True)
    replacement = store.get_run(result["run_id"])
    original = store.get_run(source["id"])
    assert original["status"] == "cancelled"
    assert original["device_ids"] == ["banc-de-test"]
    assert replacement["device_ids"] == ["local-emulator"]
    assert replacement["parameters"] == original["parameters"]
    assert replacement["workflow_version"] == original["workflow_version"]
    assert replay.replay_one(store, source["id"], apply=True)["run_id"] == result["run_id"]
    assert len(store.list_runs(100, 0)) == 2
    events = store.list_events(source["id"], 0, 100)
    assert [e["type"] for e in events] == ["run.created", "run.cancelled", "run.retried"]
    assert store.list_events(result["run_id"], 0, 100)[1]["payload"]["source_run_id"] == str(source["id"])
    with store.connect() as connection:
        assert connection.execute("SELECT count(*) AS count FROM audit_log WHERE action='run.retried'").fetchone()["count"] == 1


def test_lost_response_after_new_commit_is_repaired_without_duplicate(backlog):
    store, source = backlog
    def crash(_):
        raise RuntimeError("interrupted between commits")
    with pytest.raises(RuntimeError):
        replay.replay_one(store, source["id"], apply=True, after_submission=crash)
    assert store.get_run(source["id"])["status"] == "queued"
    assert len(store.list_runs(100, 0)) == 2
    result = replay.replay_one(store, source["id"], apply=True)
    assert result["status"] == "replayed"
    assert len(store.list_runs(100, 0)) == 2
    assert store.get_run(source["id"])["status"] == "cancelled"


def test_concurrent_repair_creates_one_replacement(backlog):
    store, source = backlog
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: replay.replay_one(store, source["id"], apply=True), range(4)))
    assert len({r["run_id"] for r in results}) == 1
    assert len(store.list_runs(100, 0)) == 2


def test_externally_cancelled_source_is_not_replayed(backlog):
    store, source = backlog
    ExecutionStore(store.dsn).cancel_run(source["id"])
    result = replay.replay_one(store, source["id"], apply=True)
    assert result["status"] == "skipped"
    assert len(store.list_runs(100, 0)) == 1


def test_disconnected_or_quarantined_target_cannot_be_replayed(backlog):
    store, source = backlog
    with store.connect() as connection:
        connection.execute("UPDATE service_heartbeats SET last_seen_at=clock_timestamp()-interval '1 minute'")
    with pytest.raises(ValueError, match="fresh confirmed"):
        replay.replay_one(store, source["id"], apply=True)
    heartbeat(store.dsn,"worker","test-worker","bench-host", metrics={"adb_status":"ready","devices":[{"serial":"emulator-5554","state":"device"}]})
    with store.connect() as connection:
        connection.execute("INSERT INTO device_leases(device_id,quarantined) VALUES('local-emulator',true)")
    with pytest.raises(ValueError, match="lease review"):
        replay.replay_one(store, source["id"], apply=True)
    assert store.get_run(source["id"])["status"] == "queued"
    assert len(store.list_runs(100, 0)) == 1
