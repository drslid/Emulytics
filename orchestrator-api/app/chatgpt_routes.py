"""Cookie-bound personal ChatGPT sign-in; never a service credential endpoint."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,ConfigDict

from .auth import AuthConfig,SESSION_COOKIE,auth_enabled
from .auth_routes import AuthRoute,client_ip
from .chatgpt_process import get_manager
from .chatgpt_store import ChatGPTStore

router = APIRouter(prefix='/console/account/chatgpt',tags=['Personal ChatGPT account'],route_class=AuthRoute)


class Login(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: UUID


class Empty(BaseModel):
    model_config = ConfigDict(extra='forbid')


def chatgpt_store():
    if not auth_enabled():
        raise HTTPException(503,'Authentification non activée')
    return ChatGPTStore(AuthConfig.load())


Store = Annotated[ChatGPTStore,Depends(chatgpt_store)]


@router.get('')
def status(request:Request,store:Store):
    return store.status(request.cookies.get(SESSION_COOKIE),get_manager(store).available)


@router.post('/login',status_code=202)
def login(payload:Login,request:Request,store:Store):
    session = request.cookies.get(SESSION_COOKIE)
    manager = get_manager(store)
    # A bearer token never supplies the personal owner, even when auth middleware allows it.
    user = store.current_user(session)
    if not user:
        raise HTTPException(401,'Connexion requise')
    if not manager.available:
        raise HTTPException(503,'Connexion ChatGPT indisponible')
    store.limit('chatgpt-login',user['id'],client_ip(request),maximum=20)
    attempt,created = store.begin(session,payload.idempotency_key,manager.instance)
    if created and not manager.start(store,session,attempt):
        store.fail(attempt['id'],manager.instance,'provider_unavailable')
    return store.status(session,manager.available)


@router.post('/cancel')
def cancel(payload:Empty,request:Request,store:Store):
    manager = get_manager(store)
    attempt_id = store.cancel(request.cookies.get(SESSION_COOKIE))
    if attempt_id:
        manager.stop(attempt_id)
    return store.status(request.cookies.get(SESSION_COOKIE),manager.available)


@router.delete('')
def disconnect(payload:Empty,request:Request,store:Store):
    manager = get_manager(store)
    attempt_id = store.cancel(request.cookies.get(SESSION_COOKIE),disconnect=True)
    if attempt_id:
        manager.stop(attempt_id)
    return store.status(request.cookies.get(SESSION_COOKIE),manager.available)
