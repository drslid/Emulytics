"""Browser authentication endpoints and protection for the whole console API."""

import io
import logging
import os
from typing import Annotated

import psycopg
import qrcode
import qrcode.image.svg
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from .access import audit_event, normalize_username, required_permission
from .auth import (
    CHALLENGE_COOKIE, CHALLENGE_SECONDS, SESSION_COOKIE, SESSION_SECONDS,
    AuthConfig, AuthStore, auth_enabled, valid_control_token,
)


logger = logging.getLogger(__name__)
PUBLIC_AUTH_PATHS = {
    "/auth/login", "/auth/verify", "/auth/recovery", "/auth/enrollment", "/auth/enrollment/qr", "/auth/logout",
    "/auth/change-password",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not auth_enabled():
            return await call_next(request)
        try:
            if request.url.path == "/health":
                response = JSONResponse({"status": "ok"})
            else:
                config = AuthConfig.load()
                service_token = valid_control_token(request)
                origin = request.headers.get("origin")
                if not service_token and origin and origin != config.origin:
                    raise HTTPException(403, "Origine refusée")
                if not service_token and request.method not in {"GET", "HEAD", "OPTIONS"}:
                    if origin != config.origin or request.headers.get("x-emulytix-client") != "console":
                        raise HTTPException(403, "Origine ou protection CSRF invalide")
                    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
                        raise HTTPException(415, "Requête JSON requise")
                if request.url.path not in PUBLIC_AUTH_PATHS and not service_token:
                    user = await run_in_threadpool(AuthStore(config).current_user, request.cookies.get(SESSION_COOKIE))
                    if not user:
                        raise HTTPException(401, "Connexion requise")
                    request.state.auth_user = user
                    permission = required_permission(request.method, request.url.path)
                    if permission != "self" and (permission is None or permission not in user["permissions"]):
                        await run_in_threadpool(record_http_audit, config, user["id"], "access.denied", 403, permission)
                        raise HTTPException(403, "Droits insuffisants")
                response = await call_next(request)
                if request.method not in {"GET", "HEAD", "OPTIONS"}:
                    actor = getattr(request.state, "auth_user", None)
                    # Mutations keep a trace without ever capturing their input or secrets.
                    action = "http.mutation" if response.status_code < 400 else "http.rejected"
                    await run_in_threadpool(record_http_audit, config, actor["id"] if actor else None,
                                            action, response.status_code, None, request.url.path)
        except HTTPException as exc:
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
        except (psycopg.Error, InvalidToken):
            logger.error("Authentication persistence or encryption unavailable")
            response = JSONResponse({"detail": "Authentification indisponible"}, status_code=503)
        response.headers.update({
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
        })
        if request.url.scheme == "https" or os.getenv("EMULYTIX_PUBLIC_ORIGIN", "").startswith("https://"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response


def record_http_audit(config: AuthConfig, actor_id, action: str, status_code: int,
                      permission: str | None = None, path: str | None = None):
    with AuthStore(config).connect() as connection:
        audit_event(connection, actor_id, action, path,
                    {"status_code": status_code, "permission": permission},
                    severity="warning" if status_code >= 400 else "info", category="access")


class AuthRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def validated(request: Request):
            try:
                return await original(request)
            except RequestValidationError:
                raise HTTPException(422, "Données de connexion invalides") from None
            except (psycopg.Error, InvalidToken):
                logger.error("Authentication persistence or encryption unavailable")
                raise HTTPException(503, "Authentification indisponible") from None

        return validated


class LoginPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$")
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("username", mode="before")
    @classmethod
    def human_username(cls, value):
        if isinstance(value, str) and 1 <= len(value.strip()) <= 120 and any(char.isalnum() for char in value):
            try:
                return normalize_username(value)
            except UnicodeEncodeError:
                pass
        raise ValueError("Invalid username")

    @field_validator("password")
    @classmethod
    def valid_unicode(cls, value: str) -> str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Invalid text") from None
        return value


class CodePayload(BaseModel):
    @field_validator("code", mode="before")
    @classmethod
    def pasted_code(cls, value):
        return "".join(value.split()) if isinstance(value, str) else value

    model_config = ConfigDict(extra="forbid", strict=True)
    code: str = Field(pattern=r"^[0-9]{6}$")


class ChangePasswordPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    password: str = Field(min_length=12, max_length=1024)
    confirm_password: str = Field(min_length=12, max_length=1024)

    @field_validator("password", "confirm_password")
    @classmethod
    def valid_unicode(cls, value: str) -> str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Invalid text") from None
        return value


class RecoveryPayload(BaseModel):
    @field_validator("code", mode="before")
    @classmethod
    def pasted_code(cls, value):
        return "".join(value.split()).replace("-", "") if isinstance(value, str) else value

    model_config = ConfigDict(extra="forbid", strict=True)
    code: str = Field(pattern=r"^[A-Fa-f0-9]{16}$")


def auth_store() -> AuthStore:
    if not auth_enabled():
        raise HTTPException(503, "Authentification non activée")
    return AuthStore(AuthConfig.load())


Store = Annotated[AuthStore, Depends(auth_store)]
router = APIRouter(prefix="/auth", tags=["Authentication"], route_class=AuthRoute)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def set_cookie(response: Response, store: AuthStore, name: str, token: str, lifetime: int):
    response.set_cookie(name, token, max_age=lifetime, httponly=True, secure=store.config.secure, samesite="strict", path="/")


def clear_challenge(response: Response, store: AuthStore):
    response.delete_cookie(CHALLENGE_COOKIE, path="/", httponly=True, secure=store.config.secure, samesite="strict")


@router.post("/login")
def login(payload: LoginPayload, request: Request, response: Response, store: Store):
    token, step = store.login(payload.username.lower(), payload.password, client_ip(request))
    set_cookie(response, store, CHALLENGE_COOKIE, token, CHALLENGE_SECONDS)
    return {"step": step}


@router.get("/enrollment")
def enrollment(request: Request, store: Store):
    return store.enrollment(request.cookies.get(CHALLENGE_COOKIE))


@router.post("/change-password")
def change_password(payload: ChangePasswordPayload, request: Request, response: Response, store: Store):
    token, step = store.change_password(
        request.cookies.get(CHALLENGE_COOKIE), payload.password, payload.confirm_password, client_ip(request),
    )
    set_cookie(response, store, CHALLENGE_COOKIE, token, CHALLENGE_SECONDS)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=store.config.secure, samesite="strict")
    return {"step": step}


@router.get("/enrollment/qr")
def enrollment_qr(request: Request, store: Store):
    data = store.enrollment(request.cookies.get(CHALLENGE_COOKIE))
    output = io.BytesIO()
    qrcode.make(data["otpauth_uri"], image_factory=qrcode.image.svg.SvgPathImage).save(output)
    return Response(output.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


def complete_auth(request: Request, response: Response, store: AuthStore, code: str, recovery: bool = False):
    token, payload = store.verify(request.cookies.get(CHALLENGE_COOKIE), code, client_ip(request), recovery)
    set_cookie(response, store, SESSION_COOKIE, token, SESSION_SECONDS)
    clear_challenge(response, store)
    return payload


@router.post("/verify")
def verify(payload: CodePayload, request: Request, response: Response, store: Store):
    return complete_auth(request, response, store, payload.code)


@router.post("/recovery")
def recovery(payload: RecoveryPayload, request: Request, response: Response, store: Store):
    return complete_auth(request, response, store, payload.code, recovery=True)


@router.get("/me")
def me(request: Request, store: Store):
    user = store.current_user(request.cookies.get(SESSION_COOKIE))
    if not user:
        raise HTTPException(401, "Connexion requise")
    return {"user": user}


@router.post("/logout")
def logout(request: Request, response: Response, store: Store):
    store.logout(request.cookies.get(SESSION_COOKIE), request.cookies.get(CHALLENGE_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=store.config.secure, samesite="strict")
    clear_challenge(response, store)
    return {"ok": True}
