import hashlib
from pathlib import Path
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.run_store import RunStore


def test_workflow_catalog_and_fleet_summary(registered, database_dsn):
    client = registered
    assert client.get("/workflows").json()["items"][0]["workflow_id"] == "go-home"
    assert client.get("/workflows?limit=0").status_code == 422
    assert client.get("/workflows?offset=1").json()["items"] == []
    fleet = client.get("/console/fleet").json()
    assert fleet["total"] == 1
    assert fleet["items"][0]["availability"] == "declared"
    assert fleet["items"][0]["active_run_id"] is None
    assert client.get("/console/summary").json() == {
        "devices_total": 1, "workflows_total": 1, "runs_total": 0,
        "runs_active": 0, "runs_needs_review": 0, "runs_succeeded": 0,
    }


def test_fleet_exposes_busy_expired_and_quarantined_without_online_claim(registered, database_dsn, run_payload):
    run = registered.post("/runs", json=run_payload).json()
    execution = run["executions"][0]["id"]
    with RunStore(database_dsn).connect() as connection:
        connection.execute(
            "INSERT INTO device_leases(device_id,lease_epoch,owner_id,execution_id,expires_at) "
            "VALUES('phone-1',1,'worker',%s,clock_timestamp()+interval '1 hour')", (execution,),
        )
    device = registered.get("/console/fleet").json()["items"][0]
    assert device["availability"] == "busy"
    assert device["active_run_id"] == run["id"]
    with RunStore(database_dsn).connect() as connection:
        connection.execute("UPDATE device_leases SET expires_at=clock_timestamp()-interval '1 hour'")
    assert registered.get("/console/fleet").json()["items"][0]["availability"] == "needs_review"
    with RunStore(database_dsn).connect() as connection:
        connection.execute("UPDATE device_leases SET owner_id=NULL,execution_id=NULL,expires_at=NULL,quarantined=true")
    assert registered.get("/console/fleet").json()["items"][0]["availability"] == "needs_review"
    assert registered.get("/console/summary").json()["runs_active"] == 1


def test_console_routes_require_control_authority(client, monkeypatch, database_dsn):
    monkeypatch.setenv("EMULYTIX_DATABASE_URL", database_dsn)
    for path in ["/console/fleet", "/console/summary", "/workflows", f"/console/executions/{uuid4()}/captures/test"]:
        assert client.get(path).status_code == 401


def test_capture_belongs_to_execution_and_is_checksum_verified(registered, database_dsn, run_payload, monkeypatch, tmp_path):
    run = registered.post("/runs", json=run_payload).json()
    execution = run["executions"][0]["id"]
    archive = tmp_path / "runs"
    folder = archive / execution / "1"
    folder.mkdir(parents=True)
    image = folder / (uuid4().hex + ".png")
    png = b"\x89PNG\r\n\x1a\nexample"
    image.write_bytes(png)
    evidence = {"steps": [{"step_id": "home", "screenshot": f"/different-worker-root/{execution}/1/{image.name}",
                           "screenshot_sha256": hashlib.sha256(png).hexdigest()}]}
    with RunStore(database_dsn).connect() as connection:
        connection.execute("UPDATE executions SET lease_epoch=1,evidence=%s WHERE id=%s", (Jsonb(evidence), execution))
    monkeypatch.setenv("EMULYTIX_ARTIFACT_ROOT", str(archive))
    url = f"/console/executions/{execution}/captures/home"
    response = registered.get(url)
    assert response.status_code == 200
    assert response.content == png
    assert response.headers["cache-control"] == "private, no-store"
    assert registered.get(f"/console/executions/{execution}/captures/unknown").status_code == 404
    image.write_bytes(png + b"modified")
    assert registered.get(url).status_code == 404
    outside = tmp_path / "outside.png"
    outside.write_bytes(png)
    image.unlink()
    image.symlink_to(outside)
    assert registered.get(url).status_code == 404
