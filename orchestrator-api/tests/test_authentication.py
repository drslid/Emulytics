from concurrent.futures import ThreadPoolExecutor

import psycopg
import pyotp
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.auth import AuthConfig, AuthStore, digest
from conftest import CONTROL_TOKEN


PASSWORD = "A long local test password 42"
ORIGIN = "http://localhost:3100"


@pytest.fixture
def auth_store(app_module, database_dsn, monkeypatch):
    monkeypatch.setenv("EMULYTIX_AUTH_ENABLED", "true")
    monkeypatch.setenv("EMULYTIX_AUTH_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("EMULYTIX_PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("EMULYTIX_COOKIE_SECURE", "false")
    monkeypatch.setenv("EMULYTIX_DATABASE_URL", database_dsn)
    return AuthStore(AuthConfig.load())


@pytest.fixture
def auth_client(app_module, auth_store):
    with TestClient(app_module.app, base_url=ORIGIN, headers={"Origin": ORIGIN, "X-Emulytix-Client": "console"}) as client:
        yield client


def create_enabled(store, username="operator"):
    user = store.create_user(username, PASSWORD)
    secret = pyotp.random_base32()
    with store.connect() as connection:
        connection.execute("UPDATE auth_users SET totp_enabled=true, totp_secret=%s WHERE id=%s",
                           (store.config.cipher.encrypt(secret.encode()).decode(), user["id"]))
    return user, secret


def current_code(store, secret, offset=0):
    with store.connect() as connection:
        epoch = connection.execute("SELECT floor(extract(epoch FROM clock_timestamp()))::bigint AS epoch").fetchone()["epoch"]
    return pyotp.TOTP(secret).at((epoch // 30 + offset) * 30)


def begin(client):
    return client.post("/auth/login", json={"username": "operator", "password": PASSWORD})


def test_enrollment_never_grants_access_before_confirming_totp(auth_client, auth_store):
    user = auth_store.create_user("operator", PASSWORD)
    assert begin(auth_client).json() == {"step": "enroll"}
    assert "emulytix_session" not in auth_client.cookies
    assert auth_client.get("/devices").status_code == 401
    enrollment = auth_client.get("/auth/enrollment")
    assert enrollment.status_code == 200
    secret = enrollment.json()["secret"]
    assert enrollment.json()["otpauth_uri"].startswith("otpauth://totp/Emulytix:")
    qr = auth_client.get("/auth/enrollment/qr")
    assert qr.status_code == 200
    assert qr.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in qr.content
    with auth_store.connect() as connection:
        stored = connection.execute("SELECT * FROM auth_users WHERE id=%s", (user["id"],)).fetchone()
    assert stored["password_hash"].startswith("$argon2id$")
    assert PASSWORD not in stored["password_hash"]
    assert secret not in stored["totp_secret"]
    response = auth_client.post("/auth/verify", json={"code": current_code(auth_store, secret)})
    assert response.status_code == 200
    assert response.json()["user"] == user
    assert len(response.json()["recovery_codes"]) == 10
    assert len(set(response.json()["recovery_codes"])) == 10
    assert auth_client.get("/devices").status_code == 200
    assert auth_client.get("/auth/enrollment").status_code == 401


def test_session_is_opaque_durable_bounded_and_revoked_on_logout(auth_client, auth_store, app_module):
    user, secret = create_enabled(auth_store)
    assert begin(auth_client).json() == {"step": "verify"}
    response = auth_client.post("/auth/verify", json={"code": current_code(auth_store, secret)})
    assert response.status_code == 200
    assert "recovery_codes" not in response.json()
    cookie = response.headers.get("set-cookie")
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Max-Age=28800" in cookie
    token = auth_client.cookies.get("emulytix_session")
    with auth_store.connect() as connection:
        stored = connection.execute("SELECT token_hash FROM auth_sessions").fetchone()
    assert stored["token_hash"] == digest(token) and stored["token_hash"] != token
    with TestClient(app_module.app, base_url=ORIGIN, cookies={"emulytix_session": token}) as restarted_client:
        assert restarted_client.get("/auth/me").json() == {"user": user}
    assert auth_client.post("/auth/logout", json={}).json() == {"ok": True}
    assert AuthStore(auth_store.config).current_user(token) is None
    assert auth_client.get("/auth/me").status_code == 401


def test_totp_replay_is_rejected_across_new_password_challenges(auth_client, auth_store):
    _, secret = create_enabled(auth_store)
    code = current_code(auth_store, secret)
    begin(auth_client)
    assert auth_client.post("/auth/verify", json={"code": code}).status_code == 200
    auth_client.post("/auth/logout", json={})
    assert begin(auth_client).json() == {"step": "verify"}
    assert auth_client.post("/auth/verify", json={"code": code}).status_code == 401
    assert auth_client.get("/devices").status_code == 401


def test_recovery_codes_are_hashed_and_usable_once(auth_client, auth_store):
    auth_store.create_user("operator", PASSWORD)
    begin(auth_client)
    secret = auth_client.get("/auth/enrollment").json()["secret"]
    response = auth_client.post("/auth/verify", json={"code": current_code(auth_store, secret)})
    code = response.json()["recovery_codes"][0]
    with auth_store.connect() as connection:
        assert connection.execute("SELECT code_hash FROM auth_recovery_codes WHERE code_hash=%s", (digest(code),)).fetchone()
        assert not connection.execute("SELECT code_hash FROM auth_recovery_codes WHERE code_hash=%s", (code,)).fetchone()
    auth_client.post("/auth/logout", json={})
    begin(auth_client)
    assert auth_client.post("/auth/recovery", json={"code": code.lower()}).status_code == 200
    auth_client.post("/auth/logout", json={})
    begin(auth_client)
    assert auth_client.post("/auth/recovery", json={"code": code}).status_code == 401


def test_wrong_login_is_generic_and_persistently_rate_limited(auth_client, auth_store):
    auth_store.create_user("operator", PASSWORD)
    unknown = auth_client.post("/auth/login", json={"username": "unknown", "password": "wrong"})
    wrong = auth_client.post("/auth/login", json={"username": "operator", "password": "wrong"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    for _ in range(9):
        assert auth_client.post("/auth/login", json={"username": "operator", "password": "wrong"}).status_code == 401
    assert begin(auth_client).status_code == 429
    with auth_store.connect() as connection:
        connection.execute("UPDATE auth_rate_limits SET window_start=clock_timestamp()-interval '16 minutes'")
    assert begin(auth_client).status_code == 200


def test_totp_attempts_are_limited_across_password_challenges(auth_client, auth_store):
    _, secret = create_enabled(auth_store)
    invalid = f"{(int(current_code(auth_store, secret)) + 1) % 1_000_000:06d}"
    begin(auth_client)
    for _ in range(10):
        assert auth_client.post("/auth/verify", json={"code": invalid}).status_code == 401
    assert auth_client.post("/auth/verify", json={"code": invalid}).status_code == 429


def test_csrf_origin_header_and_json_required(auth_client, auth_store):
    create_enabled(auth_store)
    body = {"username": "operator", "password": PASSWORD}
    assert auth_client.post("/auth/login", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert auth_client.post("/auth/login", json=body, headers={"Origin": ""}).status_code == 403
    assert auth_client.post("/auth/login", json=body, headers={"X-Emulytix-Client": ""}).status_code == 403
    assert auth_client.post("/auth/login", content="{}", headers={"Content-Type": "text/plain"}).status_code == 415
    assert auth_client.get("/devices", headers={"Origin": "https://evil.example"}).status_code == 403


def test_full_api_protected_including_legacy_routes_and_docs(auth_client):
    for path in ["/", "/devices", "/runs", "/sessions/anything/status", "/docs", "/openapi.json", "/android/status"]:
        assert auth_client.get(path).status_code == 401, path
    assert auth_client.post("/sessions", json={"name": "unauthorized"}).status_code == 401
    assert auth_client.get("/health").json() == {"status": "ok"}
    assert auth_client.get("/devices", headers={"Authorization": f"Bearer {CONTROL_TOKEN}"}).status_code == 200


def test_missing_config_fails_closed_and_secure_cookie_default(auth_client, auth_store, monkeypatch):
    for name in ["EMULYTIX_AUTH_KEY", "EMULYTIX_PUBLIC_ORIGIN", "EMULYTIX_DATABASE_URL"]:
        with monkeypatch.context() as patch:
            patch.delenv(name)
            assert auth_client.get("/devices").status_code == 503
            assert auth_client.post("/auth/login", json={"username": "operator", "password": PASSWORD}).status_code == 503
    monkeypatch.delenv("EMULYTIX_COOKIE_SECURE")
    create_enabled(auth_store)
    response = begin(auth_client)
    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


def test_non_loopback_http_or_insecure_external_cookies_rejected(auth_client, monkeypatch):
    for origin, secure in [("http://example.com", "true"), ("https://example.com", "false"),
                           ("https://[invalid", "true"), ("https://localhost:invalid", "true")]:
        monkeypatch.setenv("EMULYTIX_PUBLIC_ORIGIN", origin)
        monkeypatch.setenv("EMULYTIX_COOKIE_SECURE", secure)
        assert auth_client.get("/devices").status_code == 503


def test_expired_challenge_and_session_are_refused(auth_client, auth_store):
    _, secret = create_enabled(auth_store)
    begin(auth_client)
    with auth_store.connect() as connection:
        connection.execute("UPDATE auth_challenges SET expires_at=clock_timestamp()-interval '1 second'")
    assert auth_client.post("/auth/verify", json={"code": current_code(auth_store, secret)}).status_code == 401
    begin(auth_client)
    assert auth_client.post("/auth/verify", json={"code": current_code(auth_store, secret)}).status_code == 200
    with auth_store.connect() as connection:
        connection.execute("UPDATE auth_sessions SET expires_at=clock_timestamp()-interval '1 second'")
    assert auth_client.get("/devices").status_code == 401


def test_validation_never_echoes_password_or_code(auth_client):
    secret = "sensitive-invalid-value"
    response = auth_client.post("/auth/login", json={"username": "!", "password": secret})
    assert response.status_code == 422 and secret not in response.text
    response = auth_client.post("/auth/login", content='{"username":"operator","password":"\\ud800"}', headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    response = auth_client.post("/auth/verify", json={"code": secret})
    assert response.status_code == 422 and secret not in response.text


def test_reset_2fa_revokes_sessions_challenges_and_codes(auth_client, auth_store):
    _, secret = create_enabled(auth_store)
    begin(auth_client)
    auth_client.post("/auth/verify", json={"code": current_code(auth_store, secret)})
    assert auth_client.get("/devices").status_code == 200
    assert auth_store.reset_two_factor("operator") is True
    assert auth_client.get("/devices").status_code == 401
    assert begin(auth_client).json() == {"step": "enroll"}


def test_parallel_totp_confirmation_only_creates_one_session(auth_store):
    _, secret = create_enabled(auth_store)
    token, _ = auth_store.login("operator", PASSWORD, "test-client")
    code = current_code(auth_store, secret)

    def verify():
        try:
            auth_store.verify(token, code, "test-client")
            return "accepted"
        except Exception as exc:
            return getattr(exc, "status_code", type(exc).__name__)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: verify(), range(2)))
    assert results.count("accepted") == 1
    assert results.count(401) == 1
    with auth_store.connect() as connection:
        assert connection.execute("SELECT count(*) AS count FROM auth_sessions").fetchone()["count"] == 1
