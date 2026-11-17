from concurrent.futures import ThreadPoolExecutor
import json
from time import time
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from app import update_routes as updates
from app.access import permissions_for, required_permission


ENDPOINT = "/console/updates"
ADMIN = {"X-Test-Role": "admin"}
NOTES = "## Changements\r\n\r\n- Édition des runs\r\n- [Détails](https://github.com/drslid/Emulytics)"


@pytest.fixture
def updater(monkeypatch, tmp_path):
    requests = tmp_path / "requests"
    status = tmp_path / "status"
    requests.mkdir()
    status.mkdir()
    monkeypatch.setattr(updates, "REQUEST_FILE", requests / "request.json")
    monkeypatch.setattr(updates, "STATUS_FILE", status / "status.json")
    monkeypatch.setattr(updates, "latest_release", lambda: ("0.10.0", NOTES, False))
    monkeypatch.setenv("EMULYTIX_VERSION", "0.9.0")

    def state(name="idle", version=None, request_id=None, *, age=0, error=None):
        updates.STATUS_FILE.write_text(json.dumps({
            "state": name, "version": version, "request_id": request_id,
            "updated_at": int(time()) - age, "error": error,
        }), encoding="utf-8")

    state()
    return state


@pytest.fixture
def client(updater):
    app = FastAPI()
    app.include_router(updates.router)

    @app.middleware("http")
    async def simulate_session(request, call_next):
        role = request.headers.get("X-Test-Role")
        if role:
            request.state.auth_user = {"permissions": permissions_for(role)}
        return await call_next(request)

    return TestClient(app)


def test_only_personal_admins_may_check_and_queue(client, monkeypatch):
    def unexpected():
        pytest.fail("Denied requests must not call GitHub")

    monkeypatch.setattr(updates, "latest_release", unexpected)
    assert required_permission("GET", ENDPOINT) == required_permission("POST", ENDPOINT) == "updates.manage"
    assert client.get(ENDPOINT).status_code == 401
    assert client.post(ENDPOINT, headers={"Authorization": "Bearer service"}, json={"version": "0.10.0"}).status_code == 401
    for role in ("operator", "builder", "viewer", "auditor"):
        assert client.get(ENDPOINT, headers={"X-Test-Role": role}).status_code == 403
        assert client.post(ENDPOINT, headers={"X-Test-Role": role}, json={"version": "0.10.0"}).status_code == 403


def test_status_compares_numeric_versions_and_requires_a_live_installer(client, updater, monkeypatch):
    status = client.get(ENDPOINT, headers=ADMIN).json()
    assert status["installed_version"] == "0.9.0"
    assert status["release_url"] == updates.RELEASE_URL + "0.10.0"
    assert status["release_notes"] == NOTES
    assert status["update_available"] and status["can_install"]
    updater(age=120)
    status = client.get(ENDPOINT, headers=ADMIN).json()
    assert status["update_available"] and not status["can_install"]
    assert client.post(ENDPOINT, headers=ADMIN, json={"version": "0.10.0"}).status_code == 409
    monkeypatch.setenv("EMULYTIX_VERSION", "1.0.0")
    assert not client.get(ENDPOINT, headers=ADMIN).json()["update_available"]


def test_status_exposes_null_when_the_latest_release_has_no_notes(client, monkeypatch):
    monkeypatch.setattr(updates, "latest_release", lambda: ("0.10.0", None, False))
    status = client.get(ENDPOINT, headers=ADMIN).json()
    assert status["release_notes"] is None
    assert status["update_available"] and status["can_install"]


def test_requested_version_is_stable_and_exact(client):
    for value in ("0.10.0-rc.1", "v0.10.0", "00.10.0", "../../main"):
        assert client.post(ENDPOINT, headers=ADMIN, json={"version": value}).status_code == 422
    assert client.post(ENDPOINT, headers=ADMIN, json={"version": "0.9.0"}).status_code == 409
    assert client.post(ENDPOINT, headers=ADMIN, json={"version": "0.10.0", "url": "https://other.example"}).status_code == 422
    assert not updates.REQUEST_FILE.exists()


def test_duplicate_submission_reuses_the_same_request_and_recovers_after_restart(client, updater, monkeypatch):
    release = {"version": "0.10.0"}
    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = [executor.submit(client.post, ENDPOINT, headers=ADMIN, json=release) for _ in range(2)]
        assert [job.result().status_code for job in jobs] == [202, 202]
    queued = json.loads(updates.REQUEST_FILE.read_text(encoding="utf-8"))
    assert queued["version"] == release["version"]
    assert UUID(queued["id"]).version == 4
    assert client.get(ENDPOINT, headers=ADMIN).json()["state"] == "queued"

    updater("installing", queued["version"], queued["id"])
    installing = client.get(ENDPOINT, headers=ADMIN).json()
    assert installing["state"] == "installing" and not installing["can_install"]
    assert client.post(ENDPOINT, headers=ADMIN, json={"version": "0.11.0"}).status_code == 409

    updates.REQUEST_FILE.unlink()
    updater("installed", queued["version"], queued["id"])
    monkeypatch.setenv("EMULYTIX_VERSION", "0.10.0")
    installed = client.get(ENDPOINT, headers=ADMIN).json()
    assert installed["state"] == "installed" and installed["target_version"] == "0.10.0"
    assert not installed["update_available"]


def test_failure_is_bounded_and_can_be_retried(client, updater):
    updater("failed", "0.10.0", error="/private/path with secret")
    failure = client.get(ENDPOINT, headers=ADMIN).json()
    assert failure["state"] == "failed" and failure["error"] is None and failure["can_install"]
    assert client.post(ENDPOINT, headers=ADMIN, json={"version": "0.10.0"}).status_code == 202
    assert client.get(ENDPOINT, headers=ADMIN).json()["state"] == "queued"


@pytest.mark.parametrize(("status", "payload", "expected"), [
    (200, {"tag_name": "v0.10.0", "draft": False, "prerelease": False, "html_url": "https://other.example", "body": NOTES}, ("0.10.0", NOTES)),
    (200, {"tag_name": "v0.10.0", "draft": False, "prerelease": False, "body": " \r\n"}, ("0.10.0", None)),
    (200, {"tag_name": "v0.10.0", "draft": False, "prerelease": False}, ("0.10.0", None)),
    (200, {"tag_name": "v0.10.0", "draft": False, "prerelease": False, "body": {}}, ("0.10.0", None)),
    (200, {"tag_name": "v0.10.0", "draft": False, "prerelease": False, "body": "x" * 20_000}, ("0.10.0", "x" * 16_000)),
    (404, {}, (None, None)),
    (200, {"tag_name": "v0.10.0-rc.1", "draft": False, "prerelease": True}, ValueError),
    (200, {"tag_name": "android-v0.9.0", "draft": False, "prerelease": False}, ValueError),
    (302, {}, httpx.HTTPStatusError),
])
def test_release_discovery_validates_stable_tag_and_fixed_origin(monkeypatch, status, payload, expected):
    def response(request):
        assert request.method == "GET"
        assert str(request.url) == updates.RELEASES_API
        return httpx.Response(status, json=payload, headers={"location": "https://other.example"})

    with httpx.Client(transport=httpx.MockTransport(response)) as github:
        def stream(method, url, **options):
            assert options["follow_redirects"] is False
            return github.stream(method, url, headers=options["headers"])

        monkeypatch.setattr(updates.httpx, "stream", stream)
        if isinstance(expected, type):
            with pytest.raises(expected):
                updates._fetch_release()
        else:
            assert updates._fetch_release() == expected


def test_provider_failure_is_cached_briefly_and_never_enables_installation(monkeypatch):
    monkeypatch.setattr(updates, "_release_cache", (0, "0.9.0", "Old notes", False))
    calls = []

    def unavailable():
        calls.append(True)
        raise httpx.ConnectError("network unavailable")

    monkeypatch.setattr(updates, "_fetch_release", unavailable)
    assert updates.latest_release() == (None, None, True)
    assert updates.latest_release() == (None, None, True)
    assert calls == [True]


def test_latest_version_and_release_notes_share_one_cached_fetch(monkeypatch):
    ticks = [0]
    results = iter([("0.10.0", NOTES), ("0.11.0", None)])
    monkeypatch.setattr(updates, "_release_cache", (0, None, None, False))
    monkeypatch.setattr(updates, "monotonic", lambda: ticks[0])
    monkeypatch.setattr(updates, "_fetch_release", lambda: next(results))
    assert updates.latest_release() == ("0.10.0", NOTES, False)
    ticks[0] += 299
    assert updates.latest_release() == ("0.10.0", NOTES, False)
    ticks[0] += 1
    assert updates.latest_release() == ("0.11.0", None, False)
