"""Authenticated managed-emulator configuration and queued operations."""
from typing import Annotated
from uuid import UUID
import logging

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
import psycopg
from pydantic import Field, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

from . import apk_catalog, apkmirror_catalog, aptoide_catalog, aurora_store, fdroid_catalog
from .emulator_store import EmulatorStore
from .emulator_hardware import EmulatorHardware
from .run_models import Contract, Identifier
from .run_routes import ControlRoute, Store

router = APIRouter(prefix='/console',tags=['Managed emulators'],route_class=ControlRoute)
logger = logging.getLogger(__name__)


class Configuration(Contract):
    application_ids: list[Annotated[str,Field(min_length=1,max_length=128)]] = Field(default_factory=lambda:['chrome'],max_length=12)
    hardware: EmulatorHardware | None = None

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


class FdroidImport(Contract):
    package_name: Annotated[str, Field(max_length=200, pattern=f'^{apk_catalog.PACKAGE_NAME_PATTERN}$')]
    sha256: Annotated[str, Field(pattern=f'^{fdroid_catalog.SHA256_PATTERN}$')]


class AptoideImport(Contract):
    package_name: Annotated[str, Field(max_length=200, pattern=f'^{apk_catalog.PACKAGE_NAME_PATTERN}$')]
    version_id: Annotated[str, Field(pattern=r'^[1-9][0-9]{0,11}:[a-f0-9]{32}$')]


def _actor(request):
    user = getattr(request.state,'auth_user',None)
    return UUID(str(user['id'])) if user else None


@router.get('/emulators')
def emulators(store: Store):
    return EmulatorStore(store.dsn).list_emulators()


@router.post('/emulators',status_code=201)
def create_emulator(payload: CreateEmulator, request: Request, response: Response, store: Store):
    value, created = EmulatorStore(store.dsn).create_emulator(payload.name,payload.host_id,payload.application_ids,payload.idempotency_key,_actor(request),hardware=payload.hardware.model_dump() if payload.hardware else None)
    response.status_code = 201 if created else 200
    return value


@router.post('/emulators/{device_id}/configuration')
def configuration(device_id: Identifier, payload: Configuration, request: Request, store: Store):
    return EmulatorStore(store.dsn).configure(device_id,payload.application_ids,_actor(request),hardware=payload.hardware.model_dump() if payload.hardware else None)


@router.post('/emulators/{device_id}/{action}',status_code=202)
def operation(device_id: Identifier, action: Annotated[str,Field(pattern=r'^(start|prepare|stop)$')], payload: Operation, request: Request, store: Store):
    return EmulatorStore(store.dsn).queue_operation(device_id,action,payload.idempotency_key,_actor(request))


@router.post('/applications',status_code=201)
async def upload_application(request: Request, store: Store, file: Annotated[UploadFile,File()], name: Annotated[str|None,Form(max_length=160)]=None):
    metadata = await apk_catalog.ingest_apk(file,name)
    return await run_in_threadpool(_publish_application, metadata, request, store)


@router.get('/applications/fdroid')
def search_fdroid_applications(store: Store, q: Annotated[str, Query(min_length=2, max_length=100)]):
    return fdroid_catalog.search_applications(q)


@router.post('/applications/fdroid', status_code=201)
def import_fdroid_application(payload: FdroidImport, request: Request, response: Response, store: Store):
    app, release = fdroid_catalog.find_release(payload.package_name, payload.sha256)
    existing = EmulatorStore(store.dsn).matching_application(payload.package_name, payload.sha256, _actor(request))
    if existing is not None:
        response.status_code = 200
        return existing
    metadata = fdroid_catalog.import_application(app, release)
    result = _publish_application(metadata, request, store, reuse_exact=True)
    if result['id'] != metadata['id']:
        response.status_code = 200
    return result


@router.post('/applications/aurora', status_code=201)
def import_aurora_application(request: Request, response: Response, store: Store):
    try:
        metadata = aurora_store.download_release(aurora_store.find_latest_release())
    except aurora_store.AuroraUnavailable:
        raise HTTPException(503, 'The official Aurora Store release is temporarily unavailable') from None
    except aurora_store.AuroraIncompatible:
        raise HTTPException(422, 'The latest Aurora Store APK did not pass verification') from None
    result = _publish_application(metadata, request, store, reuse_exact=True)
    if result['id'] != metadata['id']:
        response.status_code = 200
    return result


@router.get('/applications/apkmirror')
def search_apkmirror_applications(store: Store, q: Annotated[str, Query(min_length=2, max_length=100)]):
    return apkmirror_catalog.search_applications(q)


@router.get('/applications/apkmirror/versions')
def list_apkmirror_versions(store: Store, q: Annotated[str, Query(pattern=f'^{apkmirror_catalog.APP_ID}$')]):
    return apkmirror_catalog.list_versions(q)


@router.get('/applications/aptoide')
def search_aptoide_applications(store: Store, q: Annotated[str, Query(min_length=2, max_length=100)]):
    return aptoide_catalog.search_applications(q)


@router.get('/applications/aptoide/versions')
def list_aptoide_versions(store: Store, q: Annotated[str, Query(max_length=200, pattern=f'^{apk_catalog.PACKAGE_NAME_PATTERN}$')]):
    return aptoide_catalog.list_versions(q)


@router.post('/applications/aptoide', status_code=201)
def import_aptoide_application(payload: AptoideImport, request: Request, response: Response, store: Store):
    release = aptoide_catalog.find_release(payload.package_name, payload.version_id)
    label = f'{release.name[:157-len(release.version_name)]} ({release.version_name})'
    expected = apk_catalog.ExpectedApk(
        release.package_name, release.version_code, None, release.size_bytes,
        md5=release.md5, signer_sha1=release.signer_sha1, signer_sha256=release.signer_sha256,
    )
    metadata = apk_catalog.download_store_apk(release.url, label, expected)
    result = _publish_application(metadata, request, store, reuse_exact=True)
    if result['id'] != metadata['id']:
        response.status_code = 200
    return result


def _publish_application(metadata: dict, request: Request, store: Store, *, reuse_exact: bool = False):
    try:
        result = EmulatorStore(store.dsn).add_application(metadata, _actor(request), reuse_exact=reuse_exact)
    except HTTPException as error:
        if error.status_code in {401,403,409,422}:
            apk_catalog.discard_rejected_import(metadata)
        raise
    except psycopg.IntegrityError:
        apk_catalog.discard_rejected_import(metadata)
        raise
    except psycopg.Error:
        # A lost commit acknowledgement can still mean the catalogue row exists.
        logger.warning('APK publication could not be confirmed; imported artifact retained')
        raise
    if reuse_exact and result['id'] != metadata['id']:
        apk_catalog.discard_rejected_import(metadata)
    return result
