"""Check the stable Emulytics release and queue it for the host installer."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
from tempfile import NamedTemporaryFile
from threading import Lock
from time import monotonic, time
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
import httpx
from pydantic import Field

from .auth_routes import AuthRoute
from .run_models import Contract


RELEASES_API = "https://api.github.com/repos/drslid/Emulytics/releases/latest"
RELEASE_URL = "https://github.com/drslid/Emulytics/releases/tag/v"
VERSION_PATTERN = r"(?:0|[1-9][0-9]{0,5})(?:\.(?:0|[1-9][0-9]{0,5})){2}"
REQUEST_FILE = Path("/updates/requests/request.json")
STATUS_FILE = Path("/updates/status/status.json")
STATUS_MAX_AGE = 90

_release_lock = Lock()
_release_cache: tuple[float, str | None, bool] = (0, None, False)


def require_update_admin(request: Request) -> None:
    user = getattr(request.state, "auth_user", None)
    if user is None:
        raise HTTPException(401, "Connexion personnelle requise")
    if "updates.manage" not in user["permissions"]:
        raise HTTPException(403, "Droits insuffisants")


router = APIRouter(prefix="/console/updates", tags=["Updates"], route_class=AuthRoute,
                   dependencies=[Depends(require_update_admin)])


class UpdateRequest(Contract):
    version: Annotated[str, Field(max_length=20, pattern=f"^{VERSION_PATTERN}$")]


def version_key(value: object) -> tuple[int, ...]:
    if not isinstance(value, str) or not re.fullmatch(VERSION_PATTERN, value):
        return ()
    return tuple(int(part) for part in value.split("."))


def _fetch_release() -> str | None:
    deadline = monotonic() + 7
    body = bytearray()
    with httpx.stream("GET", RELEASES_API, timeout=httpx.Timeout(5, connect=2),
                      headers={"Accept": "application/vnd.github+json", "User-Agent": "Emulytics"},
                      trust_env=False, follow_redirects=False) as response:
        if response.status_code == 404:
            return None
        response.raise_for_status()
        for chunk in response.iter_bytes():
            if monotonic() > deadline or len(body) + len(chunk) > 128 * 1024:
                raise ValueError("Release response exceeds its limits")
            body.extend(chunk)
    release = json.loads(body)
    if not isinstance(release, dict) or release.get("draft") is not False or release.get("prerelease") is not False:
        raise ValueError("Invalid stable release")
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v") or not version_key(tag[1:]):
        raise ValueError("Invalid stable release tag")
    return tag[1:]


def latest_release() -> tuple[str | None, bool]:
    global _release_cache
    with _release_lock:
        if monotonic() >= _release_cache[0]:
            try:
                version = _fetch_release()
            except (httpx.HTTPError, OSError, ValueError, RecursionError):
                _release_cache = (monotonic() + 30, None, True)
            else:
                _release_cache = (monotonic() + 300, version, False)
        return _release_cache[1], _release_cache[2]


def _read_record(path: Path) -> dict:
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                return {}
            data = source.read(1025)
        value = json.loads(data) if len(data) <= 1024 else None
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, RecursionError):
        return {}


def update_status() -> dict:
    installed = os.getenv("EMULYTIX_VERSION", "")
    latest, check_failed = latest_release()
    available = bool(version_key(installed) and version_key(latest) > version_key(installed))
    status = _read_record(STATUS_FILE)
    pending = _read_record(REQUEST_FILE)
    state = status.get("state")
    target = status.get("version")
    error = status.get("error")
    valid_state = isinstance(state, str) and state in {"idle", "installing", "installed", "failed"}
    if not valid_state:
        state = "idle"
    if version_key(pending.get("version")) and pending.get("id") != status.get("request_id"):
        state, target, error = "queued", pending["version"], None
    updated_at = status.get("updated_at")
    fresh = type(updated_at) is int and 0 <= time() - updated_at <= STATUS_MAX_AGE
    can_install = available and valid_state and fresh and state not in {"queued", "installing"} and not os.path.lexists(REQUEST_FILE)
    return {
        "installed_version": installed if version_key(installed) else None,
        "latest_version": latest,
        "update_available": available,
        "can_install": can_install,
        "release_url": RELEASE_URL + latest if latest else None,
        "state": state,
        "target_version": target if version_key(target) else None,
        "error": error if isinstance(error, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,39}", error) else None,
        "check_failed": check_failed,
    }


def _queue(version: str) -> None:
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(dir=REQUEST_FILE.parent, prefix=".request-", delete=False) as output:
            temporary = Path(output.name)
            output.write(json.dumps({"version": version, "id": str(uuid4())}).encode())
            output.flush()
            os.fsync(output.fileno())
        # The installation owner can consume requests written by the container.
        temporary.chmod(0o644)
        os.link(temporary, REQUEST_FILE)
        if hasattr(os, "O_DIRECTORY"):
            directory = os.open(REQUEST_FILE.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@router.get("")
def get_updates():
    return update_status()


@router.post("", status_code=202)
def request_update(payload: UpdateRequest):
    pending = _read_record(REQUEST_FILE).get("version")
    if pending == payload.version:
        return {"accepted": True}
    status = update_status()
    if status["check_failed"]:
        raise HTTPException(503, "Vérification de la release indisponible")
    if not status["update_available"] or payload.version != status["latest_version"]:
        raise HTTPException(409, "Cette version n’est plus proposée")
    if not status["can_install"]:
        if _read_record(REQUEST_FILE).get("version") == payload.version:
            return {"accepted": True}
        raise HTTPException(409, "Le service de mise à jour est indisponible ou occupé")
    try:
        _queue(payload.version)
    except FileExistsError:
        if _read_record(REQUEST_FILE).get("version") != payload.version:
            raise HTTPException(409, "Une mise à jour est déjà demandée") from None
    except OSError:
        raise HTTPException(503, "Impossible de transmettre la mise à jour") from None
    return {"accepted": True}
