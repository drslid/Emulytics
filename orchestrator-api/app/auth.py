"""Password + TOTP authentication; only complete MFA creates a session."""

from __future__ import annotations

import hashlib
import os
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlparse
from uuid import uuid4

import psycopg
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request
from psycopg.rows import dict_row

from .access import audit_event, normalize_username, permissions_for


SESSION_COOKIE = "emulytix_session"
CHALLENGE_COOKIE = "emulytix_challenge"
SESSION_SECONDS = 8 * 60 * 60
CHALLENGE_SECONDS = 5 * 60
PASSWORD_HASHER = PasswordHasher()
_DUMMY_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))


def auth_enabled() -> bool:
    return os.getenv("EMULYTIX_AUTH_ENABLED", "false").lower() == "true"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def valid_control_token(request: Request) -> bool:
    scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
    expected = os.getenv("EMULYTIX_CONTROL_TOKEN", "")
    return bool(expected and scheme.lower() == "bearer" and secrets.compare_digest(supplied.encode(), expected.encode()))


@dataclass(frozen=True)
class AuthConfig:
    dsn: str
    cipher: Fernet
    origin: str
    secure: bool

    @classmethod
    def load(cls) -> AuthConfig:
        dsn = os.getenv("EMULYTIX_DATABASE_URL", "")
        key = os.getenv("EMULYTIX_AUTH_KEY", "")
        origin = os.getenv("EMULYTIX_PUBLIC_ORIGIN", "")
        secure = os.getenv("EMULYTIX_COOKIE_SECURE", "true").lower() != "false"
        try:
            parsed = urlparse(origin)
            parsed.port  # Validate malformed or out-of-range ports before accepting an origin.
            cipher = Fernet(key.encode())
            valid_origin = (
                parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username
                and not parsed.password and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment
            )
            if not dsn or not valid_origin or origin.endswith("/"):
                raise ValueError("Missing configuration")
            if not secure and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
                raise ValueError("Insecure cookies require a loopback HTTP origin")
            if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("HTTPS required")
            return cls(dsn, cipher, origin, secure)
        except (ValueError, TypeError):
            raise HTTPException(503, "Authentification indisponible : configuration requise") from None


class AuthStore:
    def __init__(self, config: AuthConfig):
        self.config = config

    @contextmanager
    def connect(self):
        with psycopg.connect(self.config.dsn, connect_timeout=3, row_factory=dict_row) as connection:
            connection.execute("SET LOCAL statement_timeout = '5s'")
            connection.execute("SET LOCAL lock_timeout = '2s'")
            yield connection

    def limit(self, action: str, identity: str, ip: str, maximum: int = 10) -> None:
        # Commit counters before checking credentials, including rejected attempts.
        blocked = False
        with self.connect() as connection:
            connection.execute("DELETE FROM auth_rate_limits WHERE window_start < clock_timestamp() - interval '1 day'")
            for key, ceiling in [(f"{action}:account:{identity}", maximum), (f"{action}:ip:{ip}", 50)]:
                row = connection.execute(
                    "INSERT INTO auth_rate_limits(bucket_key, attempts) VALUES (%s, 1) "
                    "ON CONFLICT(bucket_key) DO UPDATE SET "
                    "attempts = CASE WHEN auth_rate_limits.window_start < clock_timestamp() - interval '15 minutes' "
                    "THEN 1 ELSE auth_rate_limits.attempts + 1 END, "
                    "window_start = CASE WHEN auth_rate_limits.window_start < clock_timestamp() - interval '15 minutes' "
                    "THEN clock_timestamp() ELSE auth_rate_limits.window_start END RETURNING attempts",
                    (digest(key),),
                ).fetchone()
                blocked |= row["attempts"] > ceiling
        if blocked:
            raise HTTPException(429, "Trop de tentatives. Réessayez dans 15 minutes.", headers={"Retry-After": "900"})

    def create_user(self, username: str, password: str, role: str = "admin") -> dict:
        self.validate_password(password)
        with self.connect() as connection:
            connection.execute("SELECT singleton FROM auth_installation WHERE singleton FOR UPDATE").fetchone()
            row = connection.execute(
                "INSERT INTO auth_users(id, username, display_name, password_hash, role) VALUES(%s,%s,%s,%s,%s) RETURNING *",
                (uuid4(), normalize_username(username), username.strip(), PASSWORD_HASHER.hash(password), role),
            ).fetchone()
            connection.execute("UPDATE auth_installation SET bootstrapped=true WHERE singleton")
            audit_event(connection, None, "user.created", str(row["id"]), {"role": role})
        return self.public_user(row)

    @staticmethod
    def validate_password(password: str) -> None:
        if not isinstance(password, str) or not 12 <= len(password) <= 1024:
            raise ValueError("Le mot de passe doit contenir entre 12 et 1024 caractères.")
        try:
            password.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Le mot de passe contient un caractère invalide.") from None

    def bootstrap_user(self, password: str) -> bool:
        self.validate_password(password)
        with self.connect() as connection:
            state = connection.execute("SELECT bootstrapped FROM auth_installation WHERE singleton FOR UPDATE").fetchone()
            if state["bootstrapped"]:
                return False
            if connection.execute("SELECT 1 FROM auth_users LIMIT 1").fetchone():
                connection.execute("UPDATE auth_installation SET bootstrapped=true WHERE singleton")
                return False
            connection.execute(
                "INSERT INTO auth_users(id,username,display_name,password_hash,password_change_required) VALUES(%s,'admin','admin',%s,true)",
                (uuid4(), PASSWORD_HASHER.hash(password)),
            )
            connection.execute("UPDATE auth_installation SET bootstrapped=true WHERE singleton")
        return True

    @staticmethod
    def issue_challenge(connection, user_id, purpose: str) -> str:
        token = secrets.token_urlsafe(32)
        connection.execute("DELETE FROM auth_challenges WHERE user_id = %s OR expires_at <= clock_timestamp()", (user_id,))
        connection.execute(
            "INSERT INTO auth_challenges(token_hash,user_id,purpose,expires_at) VALUES(%s,%s,%s,clock_timestamp() + interval '5 minutes')",
            (digest(token), user_id, purpose),
        )
        return token

    @staticmethod
    def public_user(row: dict) -> dict:
        return {"id": str(row["id"]), "username": row["username"],
                "display_name": row["display_name"], "role": row["role"],
                "permissions": permissions_for(row["role"]), "active": row["active"]}

    def login(self, username: str, password: str, ip: str) -> tuple[str, str]:
        username = normalize_username(username)
        self.limit("login", username, ip)
        with self.connect() as connection:
            user = connection.execute("SELECT * FROM auth_users WHERE username = %s FOR UPDATE", (username,)).fetchone()
            try:
                PASSWORD_HASHER.verify(user["password_hash"] if user else _DUMMY_HASH, password)
            except (VerificationError, InvalidHashError):
                raise HTTPException(401, "Identifiant ou mot de passe incorrect") from None
            if not user or not user["active"]:
                raise HTTPException(401, "Identifiant ou mot de passe incorrect")
            if PASSWORD_HASHER.check_needs_rehash(user["password_hash"]):
                connection.execute("UPDATE auth_users SET password_hash = %s WHERE id = %s", (PASSWORD_HASHER.hash(password), user["id"]))
            purpose = "change_password" if user["password_change_required"] else "verify" if user["totp_enabled"] else "enroll"
            if purpose != "change_password" and not user["totp_secret"]:
                encrypted = self.config.cipher.encrypt(pyotp.random_base32().encode()).decode()
                connection.execute("UPDATE auth_users SET totp_secret = %s WHERE id = %s", (encrypted, user["id"]))
            token = self.issue_challenge(connection, user["id"], purpose)
            audit_event(connection, user["id"], "auth.password.accepted", str(user["id"]))
        return token, purpose

    def _challenge_user(self, connection, token: str | None):
        if not token or len(token) > 128:
            raise HTTPException(401, "Connexion à reprendre")
        row = connection.execute(
            "SELECT u.*, c.purpose, c.token_hash AS challenge_hash, "
            "floor(extract(epoch FROM clock_timestamp()))::bigint AS current_epoch "
            "FROM auth_users u JOIN auth_challenges c ON c.user_id = u.id "
            "WHERE c.token_hash = %s AND c.expires_at > clock_timestamp() FOR UPDATE OF u, c",
            (digest(token),),
        ).fetchone()
        if not row or not row["active"]:
            raise HTTPException(401, "Connexion à reprendre")
        return row

    def change_password(self, challenge: str | None, password: str, confirm_password: str, ip: str) -> tuple[str, str]:
        try:
            self.validate_password(password)
            self.validate_password(confirm_password)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if password != confirm_password:
            raise HTTPException(422, "Les mots de passe diffèrent")
        with self.connect() as connection:
            user = self._challenge_user(connection, challenge)
            if user["purpose"] != "change_password" or not user["password_change_required"]:
                raise HTTPException(403, "Changement de mot de passe indisponible")
            identity = user["username"]
        self.limit("change-password", identity, ip)
        with self.connect() as connection:
            user = self._challenge_user(connection, challenge)
            if user["purpose"] != "change_password" or not user["password_change_required"]:
                raise HTTPException(403, "Changement de mot de passe indisponible")
            try:
                same_password = PASSWORD_HASHER.verify(user["password_hash"], password)
            except VerificationError:
                same_password = False
            if same_password:
                raise HTTPException(422, "Choisissez un mot de passe différent du mot de passe temporaire")
            password_hash = PASSWORD_HASHER.hash(password)
            consumed = connection.execute(
                "DELETE FROM auth_challenges WHERE token_hash=%s AND expires_at>clock_timestamp() RETURNING user_id",
                (user["challenge_hash"],),
            ).fetchone()
            if not consumed:
                raise HTTPException(401, "Connexion à reprendre")
            connection.execute("DELETE FROM auth_sessions WHERE user_id=%s", (user["id"],))
            connection.execute(
                "UPDATE auth_users SET password_hash=%s,password_change_required=false WHERE id=%s",
                (password_hash, user["id"]),
            )
            purpose = "verify" if user["totp_enabled"] else "enroll"
            if purpose == "enroll":
                connection.execute("DELETE FROM auth_recovery_codes WHERE user_id=%s", (user["id"],))
                secret = self.config.cipher.encrypt(pyotp.random_base32().encode()).decode()
                connection.execute("UPDATE auth_users SET totp_secret=%s WHERE id=%s", (secret, user["id"]))
            token = self.issue_challenge(connection, user["id"], purpose)
            audit_event(connection, user["id"], "auth.password.changed", str(user["id"]))
        return token, purpose

    def enrollment(self, token: str | None) -> dict:
        with self.connect() as connection:
            user = self._challenge_user(connection, token)
            if user["purpose"] != "enroll" or user["totp_enabled"] or user["password_change_required"]:
                raise HTTPException(403, "Enrôlement indisponible")
            secret = self.config.cipher.decrypt(user["totp_secret"].encode()).decode()
            uri = pyotp.TOTP(secret).provisioning_uri(name=user["username"], issuer_name="Emulytix")
        return {"secret": secret, "otpauth_uri": uri}

    def verify(self, challenge: str | None, code: str, ip: str, recovery: bool = False) -> tuple[str, dict]:
        with self.connect() as connection:
            user = self._challenge_user(connection, challenge)
            if user["password_change_required"] or user["purpose"] not in {"enroll", "verify"}:
                raise HTTPException(401, "Changement de mot de passe requis")
            identity = user["username"]
        self.limit("mfa", identity, ip)
        with self.connect() as connection:
            user = self._challenge_user(connection, challenge)
            if user["password_change_required"] or user["purpose"] not in {"enroll", "verify"}:
                raise HTTPException(401, "Changement de mot de passe requis")
            recovery_codes = None
            if recovery:
                if user["purpose"] != "verify" or not user["totp_enabled"]:
                    raise HTTPException(401, "Code incorrect ou déjà utilisé")
                removed = connection.execute(
                    "DELETE FROM auth_recovery_codes WHERE user_id = %s AND code_hash = %s RETURNING code_hash",
                    (user["id"], digest(code.upper())),
                ).fetchone()
                if not removed:
                    raise HTTPException(401, "Code incorrect ou déjà utilisé")
            else:
                secret = self.config.cipher.decrypt(user["totp_secret"].encode()).decode()
                totp = pyotp.TOTP(secret)
                current_counter = user["current_epoch"] // 30
                accepted = [counter for counter in range(current_counter - 1, current_counter + 2)
                            if counter > user["totp_last_counter"] and secrets.compare_digest(totp.at(counter * 30), code)]
                if not accepted:
                    raise HTTPException(401, "Code incorrect ou déjà utilisé")
                connection.execute("UPDATE auth_users SET totp_last_counter = %s WHERE id = %s", (max(accepted), user["id"]))
                if not user["totp_enabled"]:
                    recovery_codes = [secrets.token_hex(8).upper() for _ in range(10)]
                    connection.execute("UPDATE auth_users SET totp_enabled = true WHERE id = %s", (user["id"],))
                    for item in recovery_codes:
                        connection.execute("INSERT INTO auth_recovery_codes(user_id, code_hash) VALUES(%s,%s)", (user["id"], digest(item)))
            token = secrets.token_urlsafe(32)
            consumed = connection.execute(
                "DELETE FROM auth_challenges WHERE token_hash=%s AND expires_at>clock_timestamp() RETURNING user_id",
                (user["challenge_hash"],),
            ).fetchone()
            if not consumed:
                raise HTTPException(401, "Connexion à reprendre")
            connection.execute("DELETE FROM auth_challenges WHERE user_id = %s", (user["id"],))
            connection.execute("DELETE FROM auth_sessions WHERE expires_at <= clock_timestamp()")
            connection.execute(
                "INSERT INTO auth_sessions(token_hash,user_id,expires_at) VALUES(%s,%s,clock_timestamp() + interval '8 hours')",
                (digest(token), user["id"]),
            )
            audit_event(connection, user["id"], "auth.session.created", str(user["id"]))
        payload = {"user": self.public_user(user)}
        if recovery_codes:
            payload["recovery_codes"] = recovery_codes
        return token, payload

    def current_user(self, token: str | None) -> dict | None:
        if not token or len(token) > 128:
            return None
        with self.connect() as connection:
            user = connection.execute(
                "SELECT u.* FROM auth_sessions s JOIN auth_users u ON u.id = s.user_id "
                "WHERE s.token_hash = %s AND s.expires_at > clock_timestamp() AND u.active AND u.totp_enabled AND NOT u.password_change_required",
                (digest(token),),
            ).fetchone()
        return self.public_user(user) if user else None

    def logout(self, session: str | None, challenge: str | None) -> None:
        with self.connect() as connection:
            if session:
                user = connection.execute("DELETE FROM auth_sessions WHERE token_hash = %s RETURNING user_id", (digest(session),)).fetchone()
                if user:
                    audit_event(connection, user["user_id"], "auth.session.closed", str(user["user_id"]))
            if challenge:
                connection.execute("DELETE FROM auth_challenges WHERE token_hash = %s", (digest(challenge),))

    def reset_two_factor(self, username: str) -> bool:
        with self.connect() as connection:
            user = connection.execute("SELECT id FROM auth_users WHERE username = %s FOR UPDATE", (username,)).fetchone()
            if not user:
                return False
            connection.execute("DELETE FROM auth_sessions WHERE user_id = %s", (user["id"],))
            connection.execute("DELETE FROM auth_challenges WHERE user_id = %s", (user["id"],))
            connection.execute("DELETE FROM auth_recovery_codes WHERE user_id = %s", (user["id"],))
            connection.execute("UPDATE auth_users SET totp_secret=NULL, totp_enabled=false, totp_last_counter=-1 WHERE id=%s", (user["id"],))
            audit_event(connection, None, "user.two_factor.reset", str(user["id"]))
        return True
