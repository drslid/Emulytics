"""Worker behavior is verified against PostgreSQL without needing an emulator."""

import time

import pytest


def test_worker_executes_a_queued_workflow_and_records_actions(registered, run_payload, database_dsn, tmp_path):
    from app.worker import Worker

    class ObservedDriver:
        def __init__(self, serial, before_command, poll, artifact_dir, **kwargs):
            assert serial == "emulator-5554"
            self.before = before_command
            self.after = kwargs["after_command"]

        @staticmethod
        def validate_step(step):
            assert step["action"] == "press_key"

        def execute_step(self, step):
            self.before(["adb", "-s", "emulator-5554", "shell", "input", "keyevent", "KEYCODE_HOME"], True)
            self.after("done", {"returncode": 0})
            return {"assertion": "package", "verified": True}

        def abort(self):
            pass

    created = registered.post("/runs", json=run_payload).json()
    worker = Worker(database_dsn, "host-1", lock_root=tmp_path / "locks", artifact_root=tmp_path / "artifacts",
                    driver_factory=ObservedDriver)
    assert worker.run_once() is True
    result = registered.get(f"/runs/{created['id']}").json()
    assert result["status"] == "succeeded"
    assert result["executions"][0]["status"] == "succeeded"
    assert worker.run_once() is False
    events = registered.get(f"/runs/{created['id']}/events").json()["items"]
    assert events[-1]["type"] == "execution.finished"
    assert events[-1]["payload"]["status"] == "succeeded"


def test_lease_deadline_aborts_driver_independently_of_database_poll():
    from app.worker import LeaseWatchdog

    aborted = []
    watchdog = LeaseWatchdog(time.monotonic() + 0.15, lambda: aborted.append(True))
    with watchdog:
        time.sleep(0.35)
        assert watchdog.expired.is_set()
        assert aborted == [True]


def test_device_lock_is_exclusive_and_reusable(tmp_path):
    from app.worker import device_lock

    with device_lock(tmp_path, "host", "emulator-5554") as first:
        assert first is not None
        with device_lock(tmp_path, "host", "emulator-5554") as second:
            assert second is None
    with device_lock(tmp_path, "host", "emulator-5554") as third:
        assert third is not None


def test_failed_observation_does_not_quarantine_a_device(registered, run_payload, database_dsn, tmp_path):
    from app.worker import Worker

    class FailedObserver:
        def __init__(self, serial, before_command, poll, artifact_dir, **kwargs):
            self.before = before_command
        @staticmethod
        def validate_step(step):
            pass
        def execute_step(self, step):
            self.before(["adb", "-s", "emulator-5554", "shell", "dumpsys", "window"], False)
            raise RuntimeError("Observation deadline reached before launch")
        def abort(self):
            pass

    run = registered.post("/runs", json=run_payload).json()
    Worker(database_dsn, "host-1", lock_root=tmp_path / "locks", artifact_root=tmp_path,
           driver_factory=FailedObserver).run_once()
    assert registered.get(f"/runs/{run['id']}").json()["status"] == "failed"


def test_all_steps_are_validated_before_the_first_device_action(registered, workflow_payload, run_payload,
                                                               database_dsn, tmp_path, monkeypatch):
    from app.android_driver import AndroidDriver
    from app.worker import Worker
    observed = []
    monkeypatch.setattr(AndroidDriver, "command", lambda *args, **kwargs: observed.append(True))
    workflow = {**workflow_payload, "version": 2, "steps": [*workflow_payload["steps"], {
        "id": "invalid-final-step", "action": "press_key", "args": {"keycode": "KEYCODE_HOME"},
        "assert": {"type": "unsupported"},
    }]}
    assert registered.post("/workflows", json=workflow).status_code == 201
    run = registered.post("/runs", json={**run_payload, "workflow_version": 2}).json()
    Worker(database_dsn, "host-1", lock_root=tmp_path / "locks", artifact_root=tmp_path).run_once()
    assert registered.get(f"/runs/{run['id']}").json()["status"] == "failed"
    assert observed == []
