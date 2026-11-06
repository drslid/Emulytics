from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException
import pytest

from app.auth import AuthStore, digest
from test_authentication import auth_client, auth_store, current_code


TEMPORARY = "A temporary installation password 42"
PERSONAL = "My personal password with unicode été 73"


def login(client, password=TEMPORARY):
    return client.post("/auth/login", json={"username": "admin", "password": password})


def change(client, password=PERSONAL, confirmation=None):
    return client.post("/auth/change-password", json={
        "password": password, "confirm_password": password if confirmation is None else confirmation,
    })


def test_installation_bootstrap_is_once_and_only_stores_hash(auth_store):
    assert auth_store.bootstrap_user(TEMPORARY) is True
    with auth_store.connect() as connection:
        row = connection.execute("SELECT * FROM auth_users").fetchone()
        assert row["username"] == "admin" and row["password_change_required"] is True
        assert row["password_hash"].startswith("$argon2id$") and TEMPORARY not in row["password_hash"]
        previous = row["password_hash"]
    assert AuthStore(auth_store.config).bootstrap_user("Another temporary password 97") is False
    with auth_store.connect() as connection:
        assert connection.execute("SELECT password_hash FROM auth_users").fetchone()["password_hash"] == previous
        connection.execute("DELETE FROM auth_users")
    assert auth_store.bootstrap_user(TEMPORARY) is False


def test_bootstrap_never_claims_an_existing_or_previously_used_installation(auth_store):
    auth_store.create_user("operator", PERSONAL)
    assert auth_store.bootstrap_user(TEMPORARY) is False
    with auth_store.connect() as connection:
        connection.execute("DELETE FROM auth_users")
    assert auth_store.bootstrap_user(TEMPORARY) is False


def test_bootstrap_serializes_parallel_installers(auth_store):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: auth_store.bootstrap_user(TEMPORARY), range(2)))
    assert results.count(True) == results.count(False) == 1
    with auth_store.connect() as connection:
        assert connection.execute("SELECT count(*) AS n FROM auth_users").fetchone()["n"] == 1


def test_first_access_requires_password_change_before_enrollment_or_session(auth_client, auth_store):
    auth_store.bootstrap_user(TEMPORARY)
    assert login(auth_client).json() == {"step": "change_password"}
    assert "emulytix_session" not in auth_client.cookies
    for path in ["/devices", "/auth/me", "/auth/enrollment", "/auth/enrollment/qr"]:
        assert auth_client.get(path).status_code in {401, 403}, path
    assert auth_client.post("/auth/verify", json={"code": "123456"}).status_code == 401
    assert auth_client.post("/auth/recovery", json={"code": "A" * 16}).status_code == 401
    with auth_store.connect() as connection:
        assert connection.execute("SELECT totp_secret FROM auth_users").fetchone()["totp_secret"] is None
    old_challenge = auth_client.cookies.get("emulytix_challenge")
    assert change(auth_client).json() == {"step": "enroll"}
    new_challenge = auth_client.cookies.get("emulytix_challenge")
    assert new_challenge != old_challenge
    assert auth_client.get("/devices").status_code == 401
    with auth_store.connect() as connection:
        assert not connection.execute("SELECT 1 FROM auth_challenges WHERE token_hash=%s", (digest(old_challenge),)).fetchone()
        row = connection.execute("SELECT * FROM auth_users").fetchone()
        assert row["password_change_required"] is False and row["totp_enabled"] is False
    assert login(auth_client).status_code == 401
    assert login(auth_client, PERSONAL).json() == {"step": "enroll"}
    secret = auth_client.get("/auth/enrollment").json()["secret"]
    response = auth_client.post("/auth/verify", json={"code": current_code(auth_store, secret)})
    assert response.status_code == 200 and len(response.json()["recovery_codes"]) == 10
    assert auth_client.get("/devices").status_code == 200
    auth_client.post("/auth/logout", json={})
    assert login(auth_client).status_code == 401
    assert login(auth_client, PERSONAL).json() == {"step": "verify"}


@pytest.mark.parametrize("password,confirmation", [
    ("short", "short"), (PERSONAL, PERSONAL + " mismatch"), (TEMPORARY, TEMPORARY),
])
def test_invalid_or_unchanged_password_cannot_finish_first_step(auth_client, auth_store, password, confirmation):
    auth_store.bootstrap_user(TEMPORARY)
    login(auth_client)
    response = change(auth_client, password, confirmation)
    assert response.status_code == 422
    assert password not in response.text and confirmation not in response.text
    assert auth_client.get("/auth/enrollment").status_code == 403
    with auth_store.connect() as connection:
        assert connection.execute("SELECT password_change_required FROM auth_users").fetchone()["password_change_required"] is True


def test_password_change_requires_live_matching_challenge(auth_client, auth_store):
    auth_store.bootstrap_user(TEMPORARY)
    assert change(auth_client).status_code == 401
    login(auth_client)
    with auth_store.connect() as connection:
        connection.execute("UPDATE auth_challenges SET expires_at=clock_timestamp()-interval '1 second'")
    assert change(auth_client).status_code == 401
    login(auth_client)
    assert change(auth_client).status_code == 200
    assert change(auth_client).status_code == 403


def test_parallel_password_rotation_accepts_one_result(auth_store):
    auth_store.bootstrap_user(TEMPORARY)
    token, step = auth_store.login("admin", TEMPORARY, "test-client")
    assert step == "change_password"

    def rotate(_):
        try:
            return auth_store.change_password(token, PERSONAL, PERSONAL, "test-client")[1]
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(rotate, range(2)))
    assert results.count("enroll") == 1 and results.count(401) == 1
    with auth_store.connect() as connection:
        assert connection.execute("SELECT count(*) AS n FROM auth_challenges").fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) AS n FROM auth_sessions").fetchone()["n"] == 0


def test_flag_invalidates_even_existing_mfa_session_and_reset_preserves_gate(auth_client, auth_store):
    auth_store.bootstrap_user(TEMPORARY)
    login(auth_client)
    change(auth_client)
    secret = auth_client.get("/auth/enrollment").json()["secret"]
    auth_client.post("/auth/verify", json={"code": current_code(auth_store, secret)})
    assert auth_client.get("/devices").status_code == 200
    with auth_store.connect() as connection:
        connection.execute("UPDATE auth_users SET password_change_required=true")
    assert auth_client.get("/devices").status_code == 401
    assert login(auth_client, PERSONAL).json() == {"step": "change_password"}
    assert auth_client.post("/auth/verify", json={"code": current_code(auth_store, secret, 1)}).status_code == 401
    assert auth_store.reset_two_factor("admin")
    assert login(auth_client, PERSONAL).json() == {"step": "change_password"}


def test_password_change_validation_and_csrf_do_not_echo_secrets(auth_client, auth_store):
    auth_store.bootstrap_user(TEMPORARY)
    login(auth_client)
    assert auth_client.post("/auth/change-password", json={"password": PERSONAL, "confirm_password": PERSONAL},
                            headers={"Origin": "https://evil.example"}).status_code == 403
    response = auth_client.post("/auth/change-password", content='{"password":"\\ud800aaaaaaaaaaaa","confirm_password":"private"}',
                                headers={"Content-Type": "application/json"})
    assert response.status_code == 422 and "private" not in response.text


def test_forced_rotation_revokes_sessions_and_preserves_existing_second_factor(auth_client, auth_store):
    auth_store.bootstrap_user(TEMPORARY)
    login(auth_client)
    change(auth_client)
    secret = auth_client.get("/auth/enrollment").json()["secret"]
    codes = auth_client.post("/auth/verify", json={"code": current_code(auth_store, secret)}).json()["recovery_codes"]
    old_session = auth_client.cookies.get("emulytix_session")
    assert login(auth_client, PERSONAL).json() == {"step": "verify"}
    with auth_store.connect() as connection:
        connection.execute("UPDATE auth_users SET password_change_required=true")
    assert auth_client.post("/auth/verify", json={"code": current_code(auth_store, secret, 1)}).status_code == 401
    assert login(auth_client, PERSONAL).json() == {"step": "change_password"}
    assert change(auth_client, PERSONAL + " changed").json() == {"step": "verify"}
    assert auth_store.current_user(old_session) is None
    with auth_store.connect() as connection:
        assert connection.execute("SELECT count(*) AS n FROM auth_sessions").fetchone()["n"] == 0
        assert connection.execute("SELECT count(*) AS n FROM auth_recovery_codes").fetchone()["n"] == 10
        row = connection.execute("SELECT purpose FROM auth_challenges").fetchone()
        assert row["purpose"] == "verify"
    assert auth_client.get("/devices").status_code == 401
    assert auth_client.post("/auth/recovery", json={"code": codes[0]}).status_code == 200
    assert auth_client.get("/devices").status_code == 200
