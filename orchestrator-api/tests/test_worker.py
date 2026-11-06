"""Worker behavior is verified against PostgreSQL without needing an emulator."""

import hashlib
import time
from uuid import uuid4

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


def test_step_capture_is_available_while_the_next_step_is_running(registered, workflow_payload, run_payload,
                                                                database_dsn, tmp_path, monkeypatch):
    from app.worker import Worker

    archive = tmp_path / 'runs'
    monkeypatch.setenv('EMULYTIX_ARTIFACT_ROOT', str(archive))
    workflow = {**workflow_payload, 'version': 2, 'steps': [workflow_payload['steps'][0],
                {**workflow_payload['steps'][0], 'id': 'second'}]}
    assert registered.post('/workflows', json=workflow).status_code == 201
    run = registered.post('/runs', json={**run_payload, 'workflow_version': 2}).json()
    execution_id = run['executions'][0]['id']
    png = b'\x89PNG\r\n\x1a\nexample'

    class CapturingDriver:
        def __init__(self, serial, before_command, poll, artifact_dir, **kwargs):
            self.artifacts = artifact_dir
            self.executed = []
        @staticmethod
        def validate_step(step):
            pass
        def execute_step(self, step):
            self.executed.append(step['id'])
            if step['id'] == 'second':
                current = registered.get(f"/runs/{run['id']}").json()
                assert current['status'] == 'running'
                proof = current['executions'][0]['evidence']['steps'][0]
                assert proof['step_id'] == 'home' and proof['duration_ms'] >= 0
                response = registered.get(f'/console/executions/{execution_id}/captures/home')
                assert response.status_code == 200 and response.content == png
            self.artifacts.mkdir(parents=True, exist_ok=True)
            image = self.artifacts / (uuid4().hex + '.png')
            image.write_bytes(png)
            return {'assertion_passed': True, 'screenshot': str(image),
                    'screenshot_sha256': hashlib.sha256(png).hexdigest()}
        def abort(self):
            pass

    worker = Worker(database_dsn, 'host-1', lock_root=tmp_path / 'locks', artifact_root=archive,
                    driver_factory=CapturingDriver)
    assert worker.run_once()
    result = registered.get(f"/runs/{run['id']}").json()
    assert result['status'] == 'succeeded'
    assert [step['step_id'] for step in result['executions'][0]['evidence']['steps']] == ['home', 'second']
    events = registered.get(f"/runs/{run['id']}/events").json()['items']
    assert [event['payload']['index'] for event in events if event['type'] == 'execution.step_completed'] == [1, 2]


@pytest.mark.parametrize('cancel_requested', [False, True])
def test_step_progress_handles_rejection_or_cancellation_without_another_step(registered, workflow_payload, run_payload,
                                                                            database_dsn, tmp_path, monkeypatch,
                                                                            cancel_requested):
    from app.worker import Worker

    observed = []
    workflow = {**workflow_payload, 'version': 2, 'steps': [workflow_payload['steps'][0],
                {**workflow_payload['steps'][0], 'id': 'second'}]}
    assert registered.post('/workflows', json=workflow).status_code == 201
    run = registered.post('/runs', json={**run_payload, 'workflow_version': 2}).json()

    class InterruptedDriver:
        def __init__(self, *args, **kwargs):
            pass
        @staticmethod
        def validate_step(step):
            pass
        def execute_step(self, step):
            observed.append(step['id'])
            if cancel_requested:
                worker.store.cancel_run(run['id'])
            return {'assertion_passed': True}
        def abort(self):
            observed.append('abort')

    worker = Worker(database_dsn, 'host-1', lock_root=tmp_path / 'locks', artifact_root=tmp_path,
                    driver_factory=InterruptedDriver)
    if not cancel_requested:
        monkeypatch.setattr(worker.store, 'save_progress', lambda *args: False)
    assert worker.run_once()
    assert observed == ['home', 'abort']
    result = registered.get(f"/runs/{run['id']}").json()
    assert result['status'] == ('cancelled' if cancel_requested else 'running')
    steps = result['executions'][0]['evidence'].get('steps', [])
    assert [step['step_id'] for step in steps] == (['home'] if cancel_requested else [])
