from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
from fastapi.testclient import TestClient


API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))
CONTROL_TOKEN = "emulytix-integration-test-token"


@pytest.fixture(scope="session")
def postgres_dsn():
    """Own one disposable PostgreSQL container; never connect to a configured DB."""
    name = f"emulytix-api-tests-{uuid4().hex[:12]}"
    try:
        subprocess.run(
            [
                "docker", "run", "--rm", "--detach", "--name", name,
                "--publish", "127.0.0.1::5432",
                "--tmpfs", "/var/lib/postgresql/data",
                "--env", "POSTGRES_USER=emulytix_test",
                "--env", "POSTGRES_PASSWORD=local-test-only",
                "--env", "POSTGRES_DB=emulytix_test",
                "postgres:17-alpine",
            ],
            check=True, capture_output=True, text=True, timeout=30,
        )
        inspection = subprocess.run(
            ["docker", "inspect", name],
            check=True, capture_output=True, text=True, timeout=10,
        )
        port = json.loads(inspection.stdout)[0]["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
        dsn = (
            f"postgresql://emulytix_test:local-test-only@127.0.0.1:{port}/emulytix_test"
            "?connect_timeout=2"
        )
        deadline = time.monotonic() + 25
        while True:
            try:
                with psycopg.connect(dsn):
                    break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    logs = subprocess.run(
                        ["docker", "logs", name], capture_output=True, text=True, timeout=10,
                    )
                    pytest.fail(f"Disposable PostgreSQL failed to start: {logs.stderr}")
                time.sleep(0.1)
        yield dsn
    finally:
        subprocess.run(
            ["docker", "rm", "--force", "--volumes", name],
            check=False, capture_output=True, timeout=15,
        )


@pytest.fixture
def database_dsn(postgres_dsn):
    """Separate schema per test keeps concurrent connections fully isolated."""
    schema = "test_" + uuid4().hex
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(postgres_dsn, options=f"-csearch_path={schema}")
    try:
        from app.migrate import migrate

        migrate(dsn)
        yield dsn
    finally:
        with psycopg.connect(postgres_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def app_module(monkeypatch, tmp_path):
    monkeypatch.setenv("EMULYTIX_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("EMULYTIX_CONTROL_TOKEN", CONTROL_TOKEN)
    monkeypatch.delenv("EMULYTIX_DATABASE_URL", raising=False)
    module = importlib.import_module("app.main")
    monkeypatch.setattr(module, "STORAGE_ROOT", tmp_path / "storage")
    return module


@pytest.fixture
def client(app_module):
    with TestClient(app_module.app) as value:
        yield value


@pytest.fixture
def control_client(app_module, database_dsn, monkeypatch):
    monkeypatch.setenv("EMULYTIX_DATABASE_URL", database_dsn)
    with TestClient(app_module.app, headers={"Authorization": f"Bearer {CONTROL_TOKEN}"}) as value:
        yield value


@pytest.fixture
def workflow_payload():
    return {
        "workflow_id": "go-home",
        "version": 1,
        "steps": [
            {
                "id": "home",
                "action": "press_key",
                "args": {"keycode": "KEYCODE_HOME"},
                "assert": {"type": "package", "value": "com.android.launcher3"},
            }
        ],
    }


@pytest.fixture
def run_payload():
    return {
        "workflow_id": "go-home",
        "workflow_version": 1,
        "device_ids": ["phone-1"],
        "max_concurrency": 1,
        "idempotency_key": "first-run",
        "parameters": {},
    }


@pytest.fixture
def registered(control_client, workflow_payload):
    response = control_client.post(
        "/devices",
        json={"device_id": "phone-1", "host_id": "host-1", "serial": "emulator-5554", "kind": "emulator"},
    )
    assert response.status_code == 201, response.text
    response = control_client.post("/workflows", json=workflow_payload)
    assert response.status_code == 201, response.text
    return control_client
