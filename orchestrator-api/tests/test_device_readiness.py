from types import SimpleNamespace
import subprocess

import psycopg
import pytest

from app.telemetry import heartbeat
from app.worker import adb_device_metrics


def test_adb_probe_reports_only_device_identity_and_state(monkeypatch):
    def probe(argv, **kwargs):
        assert argv == ["adb", "devices"]
        assert kwargs["timeout"] <= 3
        assert kwargs["stderr"] == subprocess.DEVNULL
        return SimpleNamespace(returncode=0, stdout="List of devices attached\nemulator-5554\tdevice\nSerialABC\tunauthorized\nOtherPhone\toffline\ninvalid/serial\tdevice\nsecret-path\tunknown-state\n")
    monkeypatch.setattr(subprocess, "run", probe)
    assert adb_device_metrics() == {"adb_status": "ready", "devices": [
        {"serial": "emulator-5554", "state": "device"},
        {"serial": "SerialABC", "state": "unauthorized"},
        {"serial": "OtherPhone", "state": "offline"},
    ]}


@pytest.mark.parametrize("outcome", ["failure", "timeout", "missing", "invalid-output"])
def test_adb_probe_failure_never_reports_a_connected_device(monkeypatch, outcome):
    def probe(*_args, **_kwargs):
        if outcome == "timeout":
            raise subprocess.TimeoutExpired("adb", 3)
        if outcome == "missing":
            raise FileNotFoundError("private path must not enter metrics")
        return SimpleNamespace(returncode=1 if outcome == "failure" else 0,
                               stdout="private diagnostic, not a device list")
    monkeypatch.setattr(subprocess, "run", probe)
    assert adb_device_metrics() == {"adb_status": "unavailable", "devices": []}


def register(client):
    result = client.post("/devices", json={"device_id": "phone", "host_id": "actual-host", "serial": "SerialABC", "kind": "physical"})
    assert result.status_code == 201


def observed(client):
    result = client.get("/console/fleet")
    assert result.status_code == 200, result.text
    return result.json()["items"][0]


def test_registration_and_worker_liveness_do_not_prove_adb_connection(control_client, database_dsn):
    register(control_client)
    initial = observed(control_client)
    assert initial["connection_status"] == "worker_offline"
    assert initial["worker_last_seen_at"] is None
    heartbeat(database_dsn, "worker", "legacy-worker", "actual-host")
    assert observed(control_client)["connection_status"] == "unknown"
    heartbeat(database_dsn, "worker", "other-host-worker", "another-host", metrics={"adb_status": "ready", "devices": [{"serial": "SerialABC", "state": "device"}]})
    assert observed(control_client)["connection_status"] == "unknown"


@pytest.mark.parametrize("reported,expected", [("device", "connected"), ("unauthorized", "unauthorized"), ("offline", "offline"), ("recovery", "offline")])
def test_fleet_reports_exact_serial_state_from_fresh_adb_observations(control_client, database_dsn, reported, expected):
    register(control_client)
    heartbeat(database_dsn, "worker", "worker", "actual-host", metrics={"adb_status": "ready", "devices": [{"serial": "SerialABC", "state": reported}]})
    item = observed(control_client)
    assert item["connection_status"] == expected
    assert item["worker_last_seen_at"]
    assert item["availability"] == "declared"
    heartbeat(database_dsn, "worker", "worker", "actual-host", metrics={"adb_status": "ready", "devices": [{"serial": "serialabc", "state": "device"}]})
    assert observed(control_client)["connection_status"] == "not_connected"


def test_expired_adb_proof_is_not_reused_after_worker_disconnect(control_client, database_dsn):
    register(control_client)
    heartbeat(database_dsn, "worker", "worker", "actual-host", metrics={"adb_status": "ready", "devices": [{"serial": "SerialABC", "state": "device"}]})
    assert observed(control_client)["connection_status"] == "connected"
    with psycopg.connect(database_dsn) as connection:
        connection.execute("UPDATE service_heartbeats SET last_seen_at=clock_timestamp()-interval '21 seconds' WHERE component='worker'")
    assert observed(control_client)["connection_status"] == "worker_offline"
    heartbeat(database_dsn, "worker", "new-worker", "actual-host", metrics={"adb_status": "unavailable", "devices": []})
    assert observed(control_client)["connection_status"] == "unknown"


def test_any_fresh_worker_can_confirm_connection_without_using_stale_proof(control_client, database_dsn):
    register(control_client)
    heartbeat(database_dsn, "worker", "observing-worker", "actual-host", metrics={"adb_status": "ready", "devices": [{"serial": "SerialABC", "state": "device"}]})
    heartbeat(database_dsn, "worker", "temporarily-disconnected-worker", "actual-host", metrics={"adb_status": "unavailable", "devices": []})
    assert observed(control_client)["connection_status"] == "connected"
