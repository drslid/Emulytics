"""Authenticated mobile control plane; Android commands belong to leased workers."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .ai_provider_settings import router as ai_provider_router
from .auth_routes import AuthMiddleware, router as auth_router
from .automation_routes import router as automation_router
from .chatgpt_process import close_manager
from .chatgpt_routes import router as chatgpt_router
from .console_routes import router as console_router
from .emulator_routes import router as emulator_router
from .fleet_routes import router as fleet_router
from .monitor_routes import router as monitor_router
from .personal_api_routes import account_router as api_keys_router, router as personal_api_router
from .profile_routes import router as profile_router
from .run_recovery import router as recovery_router
from .run_routes import router as run_router
from .screen_routes import router as screen_router
from .self_security import router as self_security_router
from .update_routes import router as update_router
from .user_routes import router as user_router
from .user_security_routes import router as user_security_router


STORAGE_ROOT = Path(os.getenv('EMULYTIX_STORAGE_ROOT', '/storage'))
app = FastAPI(
    title=os.getenv('APP_NAME', 'Emulytix Orchestrator API'),
    description='Authenticated control plane for mobile workflows, devices and execution evidence.',
    version='0.2.0',
)
for router in (
    run_router, auth_router, console_router, user_router, user_security_router,
    profile_router, automation_router, monitor_router, screen_router,
    emulator_router, self_security_router, chatgpt_router, api_keys_router,
    personal_api_router, fleet_router, recovery_router, update_router, ai_provider_router,
):
    app.include_router(router)

origin = os.getenv('EMULYTIX_PUBLIC_ORIGIN', '')
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin] if origin else [],
    allow_credentials=True,
    allow_methods=['GET', 'HEAD', 'POST', 'PATCH', 'DELETE', 'OPTIONS'],
    allow_headers=['Authorization', 'Content-Type', 'X-Emulytix-Client'],
)
app.add_middleware(AuthMiddleware)


@app.on_event('startup')
def startup() -> None:
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    from .telemetry import service_heartbeat
    app.state.heartbeat = service_heartbeat(os.getenv('EMULYTIX_DATABASE_URL', ''), 'api')
    app.state.heartbeat.__enter__()


@app.on_event('shutdown')
def stop_heartbeat() -> None:
    close_manager()
    if getattr(app.state, 'heartbeat', None):
        app.state.heartbeat.__exit__(None, None, None)


@app.get('/health')
def health() -> dict[str, str]:
    return {'status': 'ok'}
