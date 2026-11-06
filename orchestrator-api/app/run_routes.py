"""Opt-in control API. Submitted runs remain queued until a worker is implemented."""

import logging
import os
import secrets
from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .run_models import (
    ActionView, DeviceRegistration, DeviceView, EventPage, Identifier, Page, RunDetail, RunSubmission,
    RunSummary, WorkflowRegistration, WorkflowView,
)
from .run_store import RunStore
from .execution_store import ExecutionStore
from .auth import auth_enabled


logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)


def control_store(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Iterator[RunStore]:
    dsn = os.getenv("EMULYTIX_DATABASE_URL", "")
    token = os.getenv("EMULYTIX_CONTROL_TOKEN", "")
    user_session = auth_enabled() and getattr(request.state, "auth_user", None)
    if not token and not user_session:
        raise HTTPException(503, "Runs API requires EMULYTIX_CONTROL_TOKEN")
    if not user_session and (credentials is None or not secrets.compare_digest(credentials.credentials.encode(), token.encode())):
        raise HTTPException(401, "Invalid control token", headers={"WWW-Authenticate": "Bearer"})
    if not dsn:
        raise HTTPException(503, "Runs API requires EMULYTIX_DATABASE_URL")
    try:
        yield RunStore(dsn)
    except psycopg.Error as exc:
        logger.error("Runs persistence failed (SQLSTATE %s)", exc.sqlstate or "connection")
        raise HTTPException(503, "Runs database unavailable or not migrated") from None


Store = Annotated[RunStore, Depends(control_store)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=9_223_372_036_854_775_807)]


class ControlRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def validated(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as exc:
                # Do not echo arbitrary inputs (including NaN or credentials) in errors.
                detail = [{key: error[key] for key in ("loc", "msg", "type")} for error in exc.errors()]
                raise HTTPException(422, detail) from None

        return validated


router = APIRouter(tags=["Runs control plane"], route_class=ControlRoute)


@router.post("/devices", status_code=201, response_model=DeviceView)
def register_device(payload: DeviceRegistration, response: Response, store: Store) -> dict:
    record, created = store.register_device(payload)
    response.status_code = 201 if created else 200
    return record


@router.get("/devices", response_model=Page[DeviceView])
def list_devices(store: Store, limit: Limit = 100, offset: Offset = 0) -> dict:
    return {"items": store.list_devices(limit, offset), "limit": limit, "offset": offset}


@router.post("/workflows", status_code=201, response_model=WorkflowView)
def register_workflow(payload: WorkflowRegistration, response: Response, store: Store) -> dict:
    record, created = store.register_workflow(payload)
    response.status_code = 201 if created else 200
    return record


@router.get("/workflows", response_model=Page[WorkflowView])
def list_workflows(store: Store, limit: Limit = 100, offset: Offset = 0) -> dict:
    return {"items": store.list_workflows(limit, offset), "limit": limit, "offset": offset}


@router.get("/workflows/{workflow_id}/versions/{version}", response_model=WorkflowView)
def get_workflow(workflow_id: Identifier, version: Annotated[int, Path(ge=1, le=2_147_483_647)], store: Store) -> dict:
    return store.get_workflow(workflow_id, version)


@router.post("/runs", status_code=202, response_model=RunDetail)
def submit_run(payload: RunSubmission, store: Store) -> dict:
    return store.submit_run(payload)


@router.get("/runs", response_model=Page[RunSummary])
def list_runs(store: Store, limit: Limit = 100, offset: Offset = 0) -> dict:
    return {"items": store.list_runs(limit, offset), "limit": limit, "offset": offset}


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: UUID, store: Store) -> dict:
    return store.get_run(run_id)


@router.post("/runs/{run_id}/cancel", response_model=RunDetail, responses={202: {"model": RunDetail}})
def cancel_run(run_id: UUID, store: Store, response: Response, request: Request) -> dict:
    user = getattr(request.state, 'auth_user', None)
    if user and 'devices.write' not in user['permissions']:
        with store.connect() as connection:
            if connection.execute('SELECT 1 FROM emulator_operations WHERE run_id=%s', (run_id,)).fetchone():
                raise HTTPException(403, 'Device administration permission required')
    record = ExecutionStore(store.dsn).cancel_run(run_id)
    response.status_code = 202 if record["status"] == "running" else 200
    return record


@router.get("/runs/{run_id}/events", response_model=EventPage)
def list_events(run_id: UUID, store: Store, after: Offset = 0, limit: Limit = 100) -> dict:
    return {"items": store.list_events(run_id, after, limit), "limit": limit, "after": after}


@router.get("/executions/{execution_id}/actions", response_model=Page[ActionView])
def list_actions(execution_id: UUID, store: Store, limit: Limit = 100, offset: Offset = 0) -> dict:
    return {"items": ExecutionStore(store.dsn).list_actions(execution_id, limit, offset), "limit": limit, "offset": offset}
