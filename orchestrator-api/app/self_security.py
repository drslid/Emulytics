"""Self-service credentials: reauthentication, atomic factor replacement and revocation."""
import io
import re
import secrets
from typing import Annotated

import pyotp
import qrcode
import qrcode.image.svg
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .access import audit_event
from .auth import AuthStore, PASSWORD_HASHER, SESSION_COOKIE, SESSION_SECONDS, digest
from .auth_routes import AuthRoute, auth_store, clear_challenge, client_ip, set_cookie


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    current_password: str = Field(min_length=1, max_length=1024)
    code: str = Field(min_length=1, max_length=128)
    recovery: bool = False

    @field_validator("current_password")
    @classmethod
    def bounded_unicode(cls, value):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Invalid password") from None
        return value

    @field_validator("code", mode="before")
    @classmethod
    def pasted_code(cls, value):
        return "".join(value.split()).replace("-", "") if isinstance(value, str) else value

    @model_validator(mode="after")
    def code_shape(self):
        if not re.fullmatch(r"[A-Fa-f0-9]{16}" if self.recovery else r"[0-9]{6}", self.code):
            raise ValueError("Invalid security code")
        return self


class PasswordChange(Confirmation):
    new_password: str = Field(min_length=12, max_length=1024)
    confirm_password: str = Field(min_length=12, max_length=1024)

    @field_validator("new_password", "confirm_password")
    @classmethod
    def new_password_unicode(cls, value):
        return cls.bounded_unicode(value)


class NewFactorCode(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code: str = Field(pattern=r"^[0-9]{6}$")

    @field_validator("code", mode="before")
    @classmethod
    def pasted_code(cls, value):
        return "".join(value.split()) if isinstance(value, str) else value


class SelfSecurityStore(AuthStore):
    def _session_user(self, connection, session: str | None):
        if not session or len(session) > 128:
            raise HTTPException(401, "Connexion requise")
        session_hash = digest(session)
        subject = connection.execute("SELECT user_id FROM auth_sessions WHERE token_hash=%s", (session_hash,)).fetchone()
        if not subject:
            raise HTTPException(401, "Connexion requise")
        # Serialize credentials while permitting logout audit foreign-key checks.
        user = connection.execute("SELECT * FROM auth_users WHERE id=%s FOR NO KEY UPDATE", (subject["user_id"],)).fetchone()
        if not user or not user["active"] or not user["totp_enabled"] or user["password_change_required"]:
            raise HTTPException(401, "Connexion requise")
        valid = connection.execute(
            "SELECT user_id FROM auth_sessions WHERE token_hash=%s AND expires_at>clock_timestamp() FOR UPDATE",
            (session_hash,),
        ).fetchone()
        if not valid or valid["user_id"] != user["id"]:
            raise HTTPException(401, "Connexion requise")
        user["session_hash"] = session_hash
        return user

    @staticmethod
    def _live_session(connection, user):
        if not connection.execute(
            "SELECT 1 FROM auth_sessions WHERE token_hash=%s AND expires_at>clock_timestamp()", (user["session_hash"],),
        ).fetchone():
            raise HTTPException(401, "Connexion requise")

    def _limited(self, session, ip):
        with self.connect() as connection:
            user = self._session_user(connection, session)
            username = user["username"]
        # This transaction commits even when credential validation later fails.
        self.limit("account-security", username, ip)

    @staticmethod
    def _counter(connection, secret, code, last_counter=-1):
        epoch = connection.execute("SELECT floor(extract(epoch FROM clock_timestamp()))::bigint AS epoch").fetchone()["epoch"]
        totp = pyotp.TOTP(secret)
        accepted = [counter for counter in range(epoch // 30 - 1, epoch // 30 + 2)
                    if counter > last_counter and secrets.compare_digest(totp.at(counter * 30), code)]
        if not accepted:
            raise HTTPException(403, "Mot de passe ou code de confirmation incorrect")
        return max(accepted)

    def _reauthenticate(self, connection, user, payload: Confirmation, *, last_backup_allowed=True, backup_allowed=True):
        try:
            PASSWORD_HASHER.verify(user["password_hash"], payload.current_password)
        except (VerificationError, InvalidHashError):
            raise HTTPException(403, "Mot de passe ou code de confirmation incorrect") from None
        if payload.recovery:
            if not backup_allowed:
                raise HTTPException(403, "Utilisez un code de votre application d’authentification")
            count = connection.execute("SELECT COUNT(*) AS n FROM auth_recovery_codes WHERE user_id=%s", (user["id"],)).fetchone()["n"]
            if not last_backup_allowed and count < 2:
                raise HTTPException(403, "Remplacez votre application d’authentification avant de changer votre mot de passe")
            consumed = connection.execute(
                "DELETE FROM auth_recovery_codes WHERE user_id=%s AND code_hash=%s RETURNING code_hash",
                (user["id"], digest(payload.code.upper())),
            ).fetchone()
            if not consumed:
                raise HTTPException(403, "Mot de passe ou code de confirmation incorrect")
        else:
            secret = self.config.cipher.decrypt(user["totp_secret"].encode()).decode()
            counter = self._counter(connection, secret, payload.code, user["totp_last_counter"])
            connection.execute("UPDATE auth_users SET totp_last_counter=%s WHERE id=%s", (counter, user["id"]))
        self._live_session(connection, user)

    @staticmethod
    def _new_recovery_codes(connection, user_id):
        codes = [secrets.token_hex(8).upper() for _ in range(10)]
        connection.execute("DELETE FROM auth_recovery_codes WHERE user_id=%s", (user_id,))
        for code in codes:
            connection.execute("INSERT INTO auth_recovery_codes(user_id,code_hash) VALUES(%s,%s)", (user_id, digest(code)))
        return codes

    def _rotate_session(self, connection, user):
        self._live_session(connection, user)
        connection.execute("DELETE FROM auth_challenges WHERE user_id=%s", (user["id"],))
        # Pending enrollments cascade with their bound session; no stale QR survives rotation.
        connection.execute("DELETE FROM auth_sessions WHERE user_id=%s", (user["id"],))
        token = secrets.token_urlsafe(32)
        connection.execute(
            "INSERT INTO auth_sessions(token_hash,user_id,expires_at) VALUES(%s,%s,clock_timestamp()+interval '8 hours')",
            (digest(token), user["id"]),
        )
        return token

    def status(self, session):
        with self.connect() as connection:
            user = self._session_user(connection, session)
            count = connection.execute("SELECT COUNT(*) AS n FROM auth_recovery_codes WHERE user_id=%s", (user["id"],)).fetchone()["n"]
            pending = connection.execute(
                "SELECT expires_at FROM auth_pending_totp WHERE user_id=%s AND session_hash=%s AND expires_at>clock_timestamp()",
                (user["id"], user["session_hash"]),
            ).fetchone()
            return {"two_factor_enabled": True, "recovery_codes_remaining": count,
                    "pending_enrollment_expires_at": pending["expires_at"] if pending else None}

    def change_own_password(self, session, payload: PasswordChange, ip):
        if payload.new_password != payload.confirm_password:
            raise HTTPException(422, "Les mots de passe diffèrent")
        self._limited(session, ip)
        with self.connect() as connection:
            user = self._session_user(connection, session)
            self._reauthenticate(connection, user, payload, last_backup_allowed=False)
            try:
                same = PASSWORD_HASHER.verify(user["password_hash"], payload.new_password)
            except VerificationError:
                same = False
            if same:
                raise HTTPException(422, "Choisissez un nouveau mot de passe différent")
            connection.execute("UPDATE auth_users SET password_hash=%s WHERE id=%s", (PASSWORD_HASHER.hash(payload.new_password), user["id"]))
            token = self._rotate_session(connection, user)
            audit_event(connection, user["id"], "account.password.changed", str(user["id"]))
            return token

    def start_replacement(self, session, payload: Confirmation, ip):
        self._limited(session, ip)
        with self.connect() as connection:
            user = self._session_user(connection, session)
            self._reauthenticate(connection, user, payload)
            secret = self.config.cipher.encrypt(pyotp.random_base32().encode()).decode()
            row = connection.execute(
                "INSERT INTO auth_pending_totp(user_id,session_hash,secret,expires_at) "
                "VALUES(%s,%s,%s,clock_timestamp()+interval '5 minutes') "
                "ON CONFLICT(user_id) DO UPDATE SET session_hash=EXCLUDED.session_hash,secret=EXCLUDED.secret,"
                "expires_at=EXCLUDED.expires_at,created_at=clock_timestamp() RETURNING expires_at",
                (user["id"], user["session_hash"], secret),
            ).fetchone()
            audit_event(connection, user["id"], "account.two_factor.started", str(user["id"]))
            return {"ok": True, "expires_at": row["expires_at"]}

    def _pending(self, connection, user):
        pending = connection.execute(
            "SELECT * FROM auth_pending_totp WHERE user_id=%s AND session_hash=%s AND expires_at>clock_timestamp() FOR UPDATE",
            (user["id"], user["session_hash"]),
        ).fetchone()
        if not pending:
            raise HTTPException(403, "Enrôlement à reprendre")
        return pending

    def pending_enrollment(self, session):
        with self.connect() as connection:
            user = self._session_user(connection, session)
            pending = self._pending(connection, user)
            secret = self.config.cipher.decrypt(pending["secret"].encode()).decode()
            return {"secret": secret, "otpauth_uri": pyotp.TOTP(secret).provisioning_uri(name=user["username"], issuer_name="Emulytix"),
                    "expires_at": pending["expires_at"]}

    def cancel_replacement(self, session):
        with self.connect() as connection:
            user = self._session_user(connection, session)
            connection.execute("DELETE FROM auth_pending_totp WHERE user_id=%s AND session_hash=%s", (user["id"], user["session_hash"]))
            audit_event(connection, user["id"], "account.two_factor.cancelled", str(user["id"]))

    def confirm_replacement(self, session, code, ip):
        self._limited(session, ip)
        with self.connect() as connection:
            user = self._session_user(connection, session)
            pending = self._pending(connection, user)
            secret = self.config.cipher.decrypt(pending["secret"].encode()).decode()
            counter = self._counter(connection, secret, code)
            consumed = connection.execute(
                "DELETE FROM auth_pending_totp WHERE user_id=%s AND session_hash=%s AND expires_at>clock_timestamp() RETURNING user_id",
                (user["id"], user["session_hash"]),
            ).fetchone()
            if not consumed:
                raise HTTPException(403, "Enrôlement à reprendre")
            connection.execute("UPDATE auth_users SET totp_secret=%s,totp_last_counter=%s WHERE id=%s", (pending["secret"], counter, user["id"]))
            codes = self._new_recovery_codes(connection, user["id"])
            token = self._rotate_session(connection, user)
            audit_event(connection, user["id"], "account.two_factor.changed", str(user["id"]))
            return token, codes

    def regenerate_recovery_codes(self, session, payload: Confirmation, ip):
        self._limited(session, ip)
        with self.connect() as connection:
            user = self._session_user(connection, session)
            self._reauthenticate(connection, user, payload, backup_allowed=False)
            codes = self._new_recovery_codes(connection, user["id"])
            token = self._rotate_session(connection, user)
            audit_event(connection, user["id"], "account.recovery_codes.changed", str(user["id"]))
            return token, codes


def self_store(request: Request, store: Annotated[AuthStore, Depends(auth_store)]):
    if request.headers.get("authorization") or not getattr(request.state, "auth_user", None):
        raise HTTPException(403, "Session utilisateur requise")
    if request.method not in {"GET", "HEAD"} and (
        request.headers.get("origin") != store.config.origin or request.headers.get("x-emulytix-client") != "console"
    ):
        raise HTTPException(403, "Confirmation depuis la console requise")
    return SelfSecurityStore(store.config)


Store = Annotated[SelfSecurityStore, Depends(self_store)]
router = APIRouter(prefix="/console/account", tags=["Account security"], route_class=AuthRoute)


def rotated_cookie(response, store, token):
    set_cookie(response, store, SESSION_COOKIE, token, SESSION_SECONDS)
    clear_challenge(response, store)


@router.get("/security")
def status(request: Request, store: Store):
    return store.status(request.cookies.get(SESSION_COOKIE))


@router.post("/password")
def password(payload: PasswordChange, request: Request, response: Response, store: Store):
    token = store.change_own_password(request.cookies.get(SESSION_COOKIE), payload, client_ip(request))
    rotated_cookie(response, store, token)
    return {"ok": True}


@router.post("/two-factor/start")
def start(payload: Confirmation, request: Request, store: Store):
    return store.start_replacement(request.cookies.get(SESSION_COOKIE), payload, client_ip(request))


@router.get("/two-factor/enrollment")
def enrollment(request: Request, store: Store):
    return store.pending_enrollment(request.cookies.get(SESSION_COOKIE))


@router.get("/two-factor/enrollment/qr")
def qr(request: Request, store: Store):
    data = store.pending_enrollment(request.cookies.get(SESSION_COOKIE))
    output = io.BytesIO()
    qrcode.make(data["otpauth_uri"], image_factory=qrcode.image.svg.SvgPathImage).save(output)
    return Response(output.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "private, no-store"})


@router.delete("/two-factor/enrollment")
def cancel(request: Request, store: Store):
    store.cancel_replacement(request.cookies.get(SESSION_COOKIE))
    return {"ok": True}


@router.post("/two-factor/confirm")
def confirm(payload: NewFactorCode, request: Request, response: Response, store: Store):
    token, codes = store.confirm_replacement(request.cookies.get(SESSION_COOKIE), payload.code, client_ip(request))
    rotated_cookie(response, store, token)
    return {"ok": True, "recovery_codes": codes}


@router.post("/recovery-codes")
def recovery_codes(payload: Confirmation, request: Request, response: Response, store: Store):
    token, codes = store.regenerate_recovery_codes(request.cookies.get(SESSION_COOKIE), payload, client_ip(request))
    rotated_cookie(response, store, token)
    return {"ok": True, "recovery_codes": codes}
