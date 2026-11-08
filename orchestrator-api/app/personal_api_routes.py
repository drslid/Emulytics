"""Versioned external API with scoped personal keys; business operations stay shared."""
import hashlib
from contextlib import contextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response

from .api_key_store import APIKeyStore, KeyCreation
from .access import permissions_for
from .auth import AuthConfig, SESSION_COOKIE, auth_enabled
from .auth_routes import AuthRoute, client_ip
from .execution_store import ExecutionStore
from .run_models import DeviceView, EventPage, Identifier, Page, RunDetail, RunSubmission, RunSummary, WorkflowRegistration, WorkflowView
from .run_routes import Limit, Offset
from .run_store import INTERNAL_WORKFLOW_PREFIX, RunStore, fingerprint

account_router = APIRouter(prefix='/console/account/api-keys', tags=['Personal API keys'], route_class=AuthRoute)
router = APIRouter(prefix='/api/v1', tags=['Personal external API'], route_class=AuthRoute)


def key_store():
    if not auth_enabled():
        raise HTTPException(503, 'Authentification non activée')
    return APIKeyStore(AuthConfig.load())


Keys = Annotated[APIKeyStore, Depends(key_store)]


@account_router.get('')
def list_keys(request: Request, store: Keys, limit: Limit = 100, offset: Offset = 0):
    return store.list_keys(request.cookies.get(SESSION_COOKIE), limit, offset)


@account_router.post('', status_code=201)
def create_key(payload: KeyCreation, request: Request, store: Keys):
    return store.create_key(request.cookies.get(SESSION_COOKIE), payload, client_ip(request))


@account_router.delete('/{key_id}')
def revoke_key(key_id: UUID, request: Request, store: Keys):
    return store.revoke_key(request.cookies.get(SESSION_COOKIE), key_id)


def principal(request: Request, store: Keys):
    # Dependencies still fail closed if middleware is disabled or a router is mounted alone.
    value = getattr(request.state, 'api_principal', None)
    return value or store.authenticate_key(request.headers.get('authorization'))


Principal = Annotated[dict, Depends(principal)]


def scoped(value, scope):
    if scope not in value['scopes']:
        raise HTTPException(403, 'Droits insuffisants pour cette clé API')


@contextmanager
def mutation_authority(store, actor, scope):
    with store.connect() as connection:
        # Lock in the same order as account administration: user, key, then business rows.
        user = connection.execute('SELECT active,totp_enabled,password_change_required,role FROM auth_users WHERE id=%s FOR SHARE',
                                  (actor['user']['id'],)).fetchone()
        if not user or not user['active'] or not user['totp_enabled'] or user['password_change_required']:
            raise HTTPException(401, 'Clé API expirée ou révoquée')
        key = connection.execute('SELECT scopes FROM personal_api_keys WHERE id=%s AND user_id=%s '
            'AND revoked_at IS NULL AND expires_at>clock_timestamp() FOR SHARE', (actor['key_id'], actor['user']['id'])).fetchone()
        if not key:
            raise HTTPException(401, 'Clé API expirée ou révoquée')
        if scope not in set(key['scopes']).intersection(permissions_for(user['role'])):
            raise HTTPException(403, 'Droits insuffisants pour cette clé API')
        yield connection


def business_store(store: Keys):
    return RunStore(store.config.dsn)


Business = Annotated[RunStore, Depends(business_store)]


def public_run(store, run_id):
    record = store.get_run(run_id)
    if record['workflow_id'].startswith(INTERNAL_WORKFLOW_PREFIX):
        raise HTTPException(403, 'Les opérations système ne sont pas accessibles avec une clé personnelle')
    return record


@router.get('/capabilities')
def capabilities(actor: Principal):
    return {'scopes': actor['scopes'], 'limits': {'page_size': 100, 'requests_per_minute': 600}}


@router.get('/devices', response_model=Page[DeviceView])
def devices(actor: Principal, store: Business, limit: Limit = 100, offset: Offset = 0):
    scoped(actor, 'devices.read')
    return {'items': store.list_devices(limit, offset), 'limit': limit, 'offset': offset}


@router.get('/workflows', response_model=Page[WorkflowView])
def workflows(actor: Principal, store: Business, limit: Limit = 100, offset: Offset = 0):
    scoped(actor, 'workflows.read')
    return {'items': store.list_workflows(limit, offset), 'limit': limit, 'offset': offset}


@router.get('/workflows/{workflow_id}/versions/{version}', response_model=WorkflowView)
def workflow(workflow_id: Identifier, version: Annotated[int, Path(ge=1, le=2_147_483_647)], actor: Principal, store: Business):
    scoped(actor, 'workflows.read')
    if workflow_id.startswith(INTERNAL_WORKFLOW_PREFIX):
        raise HTTPException(403, 'Parcours système réservé')
    return store.get_workflow(workflow_id, version)


@router.post('/workflows', response_model=WorkflowView, status_code=201)
def publish_workflow(payload: WorkflowRegistration, actor: Principal, store: Business, response: Response):
    scoped(actor, 'workflows.publish')
    with mutation_authority(store, actor, 'workflows.publish') as connection:
        record, created = store._register_workflow(connection, payload)
    response.status_code = 201 if created else 200
    return record


@router.get('/runs', response_model=Page[RunSummary])
def runs(actor: Principal, store: Business, limit: Limit = 100, offset: Offset = 0):
    scoped(actor, 'runs.read')
    # Keep pagination consistent while excluding device-management operations at SQL level.
    with store.connect() as connection:
        items = connection.execute(
            'SELECT * FROM runs WHERE workflow_id NOT LIKE %s ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s',
            (INTERNAL_WORKFLOW_PREFIX+'%', limit, offset),
        ).fetchall()
    return {'items': items, 'limit': limit, 'offset': offset}


@router.post('/runs', response_model=RunDetail, status_code=202)
def submit(payload: RunSubmission, actor: Principal, store: Business):
    scoped(actor, 'runs.execute')
    # A client chooses its replay key; different users cannot collide or replay each other's key.
    namespaced = 'api-' + hashlib.sha256((actor['user']['id']+'\0'+payload.idempotency_key).encode()).hexdigest()
    client_key_hash = hashlib.sha256(payload.idempotency_key.encode()).hexdigest()
    request_hash = fingerprint(payload.model_dump(mode='json', exclude={'idempotency_key'}))
    with mutation_authority(store, actor, 'runs.execute') as connection:
        connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (namespaced,))
        previous = connection.execute('SELECT * FROM personal_api_run_requests WHERE user_id=%s AND client_key_hash=%s',
            (actor['user']['id'], client_key_hash)).fetchone()
        if previous:
            if previous['request_hash'] != request_hash:
                raise HTTPException(409, 'Cette demande API correspond à un autre lot')
            return store._read_run(connection, previous['run_id'])
        if connection.execute('SELECT 1 FROM runs WHERE idempotency_key=%s', (namespaced,)).fetchone():
            raise HTTPException(409, 'Cette clé est déjà utilisée par une demande antérieure')
        result = store._submit_run(connection, payload.model_copy(update={'idempotency_key': namespaced}))
        connection.execute('INSERT INTO personal_api_run_requests(user_id,client_key_hash,run_id,request_hash) VALUES(%s,%s,%s,%s)',
            (actor['user']['id'], client_key_hash, result['id'], request_hash))
        return result


@router.get('/runs/{run_id}', response_model=RunDetail)
def run(run_id: UUID, actor: Principal, store: Business):
    scoped(actor, 'runs.read')
    return public_run(store, run_id)


@router.get('/runs/{run_id}/events', response_model=EventPage)
def events(run_id: UUID, actor: Principal, store: Business, after: Offset = 0, limit: Limit = 100):
    scoped(actor, 'runs.read')
    public_run(store, run_id)
    return {'items': store.list_events(run_id, after, limit), 'limit': limit, 'after': after}


@router.post('/runs/{run_id}/cancel', response_model=RunDetail, responses={202: {'model': RunDetail}})
def cancel(run_id: UUID, actor: Principal, store: Business, response: Response):
    scoped(actor, 'runs.cancel')
    with mutation_authority(store, actor, 'runs.cancel'):
        public_run(store, run_id)
        record = ExecutionStore(store.dsn).cancel_run(run_id)
    response.status_code = 202 if record['status'] == 'running' else 200
    return record
