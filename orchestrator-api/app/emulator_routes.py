"""Authenticated managed-emulator configuration and queued operations."""
from typing import Annotated
from uuid import UUID
import logging

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
import psycopg
from pydantic import Field, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

from .emulator_store import EmulatorStore
from .run_models import Contract, Identifier
from .run_routes import ControlRoute, Store

router = APIRouter(prefix='/console',tags=['Managed emulators'],route_class=ControlRoute)
logger = logging.getLogger(__name__)


class Configuration(Contract):
    application_ids: list[Annotated[str,Field(min_length=1,max_length=128)]] = Field(default_factory=lambda:['chrome'],max_length=12)

    @model_validator(mode='after')
    def unique_applications(self):
        if len(set(self.application_ids))!=len(self.application_ids):
            raise ValueError('Applications must be unique')
        return self


class CreateEmulator(Configuration):
    name: Annotated[str,Field(min_length=1,max_length=160)]
    host_id: Identifier
    idempotency_key: Annotated[str,Field(min_length=1,max_length=128,pattern=r'^\S+$')]

    @field_validator('name','host_id',mode='before')
    @classmethod
    def trim(cls,value):
        return value.strip() if isinstance(value,str) else value


class Operation(Contract):
    idempotency_key: Annotated[str,Field(min_length=1,max_length=128,pattern=r'^\S+$')]


def _actor(request):
    user = getattr(request.state,'auth_user',None)
    return UUID(str(user['id'])) if user else None


@router.get('/emulators')
def emulators(store: Store):
    return EmulatorStore(store.dsn).list_emulators()


@router.post('/emulators',status_code=201)
def create_emulator(payload: CreateEmulator, request: Request, response: Response, store: Store):
    value, created = EmulatorStore(store.dsn).create_emulator(payload.name,payload.host_id,payload.application_ids,payload.idempotency_key,_actor(request))
    response.status_code = 201 if created else 200
    return value


@router.post('/emulators/{device_id}/configuration')
def configuration(device_id: Identifier, payload: Configuration, request: Request, store: Store):
    return EmulatorStore(store.dsn).configure(device_id,payload.application_ids,_actor(request))


@router.post('/emulators/{device_id}/{action}',status_code=202)
def operation(device_id: Identifier, action: Annotated[str,Field(pattern=r'^(start|prepare|stop)$')], payload: Operation, request: Request, store: Store):
    return EmulatorStore(store.dsn).queue_operation(device_id,action,payload.idempotency_key,_actor(request))


@router.post('/applications',status_code=201)
async def upload_application(request: Request, store: Store, file: Annotated[UploadFile,File()], name: Annotated[str|None,Form(max_length=160)]=None):
    from .apk_catalog import discard_rejected_import, ingest_apk
    metadata = await ingest_apk(file,name)
    try:
        return EmulatorStore(store.dsn).add_application(metadata,_actor(request))
    except HTTPException as error:
        if error.status_code in {401,403,409,422}:
            await run_in_threadpool(discard_rejected_import,metadata)
        raise
    except psycopg.IntegrityError:
        await run_in_threadpool(discard_rejected_import,metadata)
        raise
    except psycopg.Error:
        # A lost commit acknowledgement can still mean the catalogue row exists.
        logger.warning('APK publication could not be confirmed; imported artifact retained')
        raise
